from __future__ import annotations

import asyncio
import inspect
import logging
import re
import random
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from .geometry import quad_center, rect_center

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ViewportPoint:
    x: float
    y: float


def _quad_center_xy(quad: list[float]) -> tuple[float, float]:
    # quad is [x1,y1,x2,y2,x3,y3,x4,y4]
    xs = quad[0::2]
    ys = quad[1::2]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _get(obj: Any, *names: str) -> Any:
    for n in names:
        if obj is None:
            continue
        if isinstance(obj, dict) and n in obj:
            return obj.get(n)
        if hasattr(obj, n):
            return getattr(obj, n)
    return None


def _node_id_from(obj: Any) -> int:
    """
    Best-effort extraction of a nodeId as an int (0 if missing/unparseable).

    Note: nodriver's NodeId is typically an int subclass; callers that need to
    preserve NodeId's serialization helpers should prefer extracting the raw
    object via `_get(..., "node_id", "nodeId")`.
    """
    if obj is None:
        return 0
    if isinstance(obj, int):
        return int(obj)
    v = _get(obj, "nodeId", "node_id", "nodeid")
    if v is None:
        return 0
    try:
        return int(v)
    except Exception:
        return 0


def _root_node_id_obj_from_doc(doc: Any) -> Any:
    """
    Extract a document root node id from a DOM.getDocument response.

    Returns the raw node id object when present (e.g., nodriver NodeId), falling
    back to an int when only dict-ish shapes are available.
    """
    root_id_obj = _get(doc, "node_id", "nodeId")
    if root_id_obj is not None:
        return root_id_obj

    root = _get(doc, "root") or doc
    root_id_obj = _get(root, "node_id", "nodeId")
    if root_id_obj is not None:
        return root_id_obj
    return _node_id_from(root)


async def _dom_get_document_nodriver(page: Any, uc: Any, *, depth: int, pierce: bool) -> Any:
    dom = getattr(getattr(uc, "cdp", None), "dom", None)
    fn = getattr(dom, "get_document", None) if dom is not None else None
    if not callable(fn):
        raise AttributeError("nodriver uc.cdp.dom.get_document is not callable")

    # Prefer a shallow document (depth=1) since we only need the root nodeId to query.
    try:
        return await page.send(fn(int(depth), bool(pierce)))
    except TypeError:
        try:
            return await page.send(fn(depth=int(depth), pierce=bool(pierce)))
        except TypeError:
            return await page.send(fn())


async def _dom_get_root_node_id_obj_nodriver(page: Any, uc: Any) -> Any:
    doc = await _dom_get_document_nodriver(page, uc, depth=1, pierce=True)
    root_id_obj = _root_node_id_obj_from_doc(doc)
    if root_id_obj:
        return root_id_obj

    # Last resort: fetch the full tree if the shallow call produced an unexpected shape.
    doc = await _dom_get_document_nodriver(page, uc, depth=-1, pierce=True)
    return _root_node_id_obj_from_doc(doc)


async def _dom_get_root_node_id_int_dict(page: Any) -> int:
    msg: dict[str, Any] = {"method": "DOM.getDocument", "params": {"depth": 1, "pierce": True}}
    doc = await page.send(msg)
    root = _get(doc, "root") or {}
    return _node_id_from(root)


async def _dom_query_selector_nodriver(page: Any, uc: Any, root_id_obj: Any, selector: str) -> Any:
    dom = getattr(getattr(uc, "cdp", None), "dom", None)
    fn = getattr(dom, "query_selector", None) if dom is not None else None
    if not callable(fn):
        raise AttributeError("nodriver uc.cdp.dom.query_selector is not callable")

    try:
        return await page.send(fn(root_id_obj, selector))
    except TypeError:
        return await page.send(fn(node_id=root_id_obj, selector=selector))


async def _dom_query_selector_int_dict(page: Any, root_node_id: int, selector: str) -> int:
    msg: dict[str, Any] = {"method": "DOM.querySelector", "params": {"nodeId": int(root_node_id), "selector": selector}}
    resp = await page.send(msg)
    return _node_id_from(resp)


async def _send_dict(page: Any, method: str, params: dict[str, Any] | None = None) -> Any:
    """Send a raw dict-based CDP message via ``page.send``."""
    # Some dict-CDP shims expect a "params" key even when it's empty.
    msg: dict[str, Any] = {"method": str(method), "params": params or {}}
    return await page.send(msg)


async def _get_box_model_and_viewport_offset(
    page: Any, node_id: Any, selector: str
) -> tuple[list[float], float, float]:
    """Shared pipeline: get box-model quad and visual-viewport offset for *node_id*.

    Returns ``(quad_floats, page_x, page_y)`` where *page_x*/*page_y* are the
    visual viewport origin (for converting page coords to viewport coords).
    """
    uc = None
    try:
        import nodriver as uc  # type: ignore[assignment]
    except Exception:
        _LOG.debug("nodriver import failed in _get_box_model_and_viewport_offset", exc_info=True)
        uc = None

    # --- box model ---
    bm: Any = None
    nodriver_exc: Exception | None = None
    if uc is not None:
        fn = getattr(getattr(getattr(uc, "cdp", None), "dom", None), "get_box_model", None)
        if callable(fn):
            try:
                bm = await page.send(fn(node_id))
            except TypeError:
                try:
                    bm = await page.send(fn(node_id=node_id))
                except Exception as e:
                    nodriver_exc = e
                    bm = None
            except Exception as e:
                nodriver_exc = e
                bm = None

    if bm is None:
        try:
            bm = await _send_dict(page, "DOM.getBoxModel", {"nodeId": int(node_id)})
        except Exception:
            if nodriver_exc is not None:
                raise nodriver_exc
            raise

    # --- extract quad ---
    quad: Any = None
    if isinstance(bm, dict):
        model = (bm.get("model") or {}) if isinstance(bm.get("model"), dict) else {}
        quad = model.get("content") or model.get("border") or model.get("margin")
    else:
        for name in ("content", "border", "margin"):
            if hasattr(bm, name):
                quad = getattr(bm, name)
                if quad:
                    break

    if not quad:
        raise RuntimeError(f"DOM.getBoxModel returned no quad for selector: {selector}")

    quad_f = [float(v) for v in quad]

    # --- layout metrics (viewport offset) ---
    page_x = 0.0
    page_y = 0.0
    try:
        metrics: Any = None
        if uc is not None:
            try:
                p = getattr(getattr(uc, "cdp", None), "page", None)
                fnm = getattr(p, "get_layout_metrics", None) if p is not None else None
                if callable(fnm):
                    metrics = await page.send(fnm())
            except Exception:
                _LOG.debug("nodriver layout-metrics failed, falling back to dict CDP", exc_info=True)
                metrics = None

        if metrics is None:
            metrics = await _send_dict(page, "Page.getLayoutMetrics")

        vv: Any = {}
        if isinstance(metrics, tuple) and len(metrics) >= 2:
            vv = metrics[1]
        elif isinstance(metrics, dict):
            vv = metrics.get("visualViewport") or {}

        if isinstance(vv, dict):
            page_x = float(vv.get("pageX") or 0.0)
            page_y = float(vv.get("pageY") or 0.0)
        else:
            page_x = float(getattr(vv, "page_x", 0.0) or 0.0)
            page_y = float(getattr(vv, "page_y", 0.0) or 0.0)
    except Exception:
        _LOG.debug("layout-metrics unavailable, assuming zero viewport offset", exc_info=True)

    return quad_f, page_x, page_y


async def selector_viewport_center(page: Any, selector: str, *, within_selector: str | None = None) -> ViewportPoint:
    """
    DOM-only fallback for getting an element's viewport center.

    This avoids Runtime evaluation (which we disable in stealth_init) by using
    DOM.getDocument/querySelector/getBoxModel via `page.send`.
    """
    if not hasattr(page, "send"):
        raise AttributeError("page has no send() for CDP DOM fallback")

    node_id = await dom_query_selector_node_id(page, selector, within_selector=within_selector)
    if not node_id:
        if within_selector:
            raise RuntimeError(
                f"DOM.querySelector returned no nodeId for selector: {selector} within {within_selector}"
            )
        raise RuntimeError(f"DOM.querySelector returned no nodeId for selector: {selector}")

    quad_f, page_x, page_y = await _get_box_model_and_viewport_offset(page, node_id, selector)
    cx, cy = _quad_center_xy(quad_f)
    cx -= page_x
    cy -= page_y
    return ViewportPoint(cx, cy)


async def selector_viewport_quad(page: Any, selector: str, *, within_selector: str | None = None) -> list[float]:
    """
    DOM-only fallback for getting an element's quad in *viewport* coordinates.

    This avoids Runtime evaluation by using DOM.getDocument/querySelector/getBoxModel via `page.send`.
    """
    if not hasattr(page, "send"):
        raise AttributeError("page has no send() for CDP DOM quad")

    node_id = await dom_query_selector_node_id(page, selector, within_selector=within_selector)
    if not node_id:
        if within_selector:
            raise RuntimeError(
                f"DOM.querySelector returned no nodeId for selector: {selector} within {within_selector}"
            )
        raise RuntimeError(f"DOM.querySelector returned no nodeId for selector: {selector}")

    quad_f, page_x, page_y = await _get_box_model_and_viewport_offset(page, node_id, selector)

    if page_x or page_y:
        for i in range(0, len(quad_f), 2):
            quad_f[i] -= page_x
            quad_f[i + 1] -= page_y

    return quad_f


def _gaussian_in_range(r: random.Random, lo: float, hi: float) -> float:
    if hi <= lo:
        return float(lo)
    mean = (lo + hi) / 2.0
    sigma = (hi - lo) / 6.0  # ~99.7% within range for a normal distribution
    v = r.gauss(mean, sigma)
    if v < lo:
        return float(lo)
    if v > hi:
        return float(hi)
    return float(v)


async def selector_viewport_gaussian_point(
    page: Any,
    selector: str,
    *,
    within_selector: str | None = None,
    rng: random.Random | None = None,
) -> ViewportPoint:
    """
    Pick a target point inside the element (inner 50%) using a Gaussian distribution.
    """
    r = rng or random
    quad = await selector_viewport_quad(page, selector, within_selector=within_selector)
    xs = quad[0::2]
    ys = quad[1::2]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    # Inner 50% box (25% margin on each side).
    inner_min_x = min_x + 0.25 * (max_x - min_x)
    inner_max_x = max_x - 0.25 * (max_x - min_x)
    inner_min_y = min_y + 0.25 * (max_y - min_y)
    inner_max_y = max_y - 0.25 * (max_y - min_y)

    x = _gaussian_in_range(r, inner_min_x, inner_max_x)
    y = _gaussian_in_range(r, inner_min_y, inner_max_y)
    return ViewportPoint(x, y)


async def dom_query_selector_node_id(page: Any, selector: str, *, within_selector: str | None = None) -> int:
    """
    CDP DOM querySelector that returns a nodeId (0 if not found).
    """
    if not hasattr(page, "send"):
        raise AttributeError("page has no send() for CDP DOM query")

    # Prefer nodriver's generated CDP commands if available (page.send usually expects these).
    uc = None
    try:
        import nodriver as uc  # type: ignore[assignment]
    except Exception:
        _LOG.debug("nodriver import failed in dom_query_selector_node_id", exc_info=True)
        uc = None

    if uc is not None:
        try:
            root_id_obj: Any = await _dom_get_root_node_id_obj_nodriver(page, uc)
            if not root_id_obj:
                return 0

            # If a scope selector is provided, resolve it once under the document root and
            # then query within that subtree.
            if within_selector:
                root_id_obj = await _dom_query_selector_nodriver(page, uc, root_id_obj, within_selector)
                if not root_id_obj:
                    return 0

            q_resp = await _dom_query_selector_nodriver(page, uc, root_id_obj, selector)
            return q_resp if q_resp else 0
        except Exception:
            # If this is not a real nodriver Tab (e.g., unit test fake), fall back to dict CDP.
            _LOG.debug("nodriver querySelector failed, falling back to dict CDP", exc_info=True)

    # Generic CDP fallback (for test fakes or other drivers that accept dict messages).
    root_id = await _dom_get_root_node_id_int_dict(page)
    if not root_id:
        return 0

    if within_selector:
        within_id = await _dom_query_selector_int_dict(page, root_id, within_selector)
        if not within_id:
            return 0
        root_id = within_id

    return await _dom_query_selector_int_dict(page, root_id, selector)


async def wait_for_selector(
    page: Any,
    selector: str,
    *,
    timeout_s: float,
    within_selector: str | None = None,
    poll_s: float = 0.05,
    max_poll_s: float = 0.25,
    refresh_document_s: float = 1.0,
) -> None:
    # Prefer a CDP DOM polling loop over driver-provided wait_for(), since some
    # stacks cache a stale document nodeId across navigations (observed in nodriver).
    if hasattr(page, "send"):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(timeout_s)
        last_exc: Exception | None = None
        poll = max(0.0, float(poll_s))
        max_poll = max(poll, float(max_poll_s))

        # Strategy: Prefer nodriver CDP message objects when possible; fall back to dict-based CDP
        # for unit-test fakes / alternative driver shims.
        uc = None
        use_nodriver = False
        try:
            import nodriver as uc  # type: ignore[assignment]

            # Probe once to avoid throwing on every poll when page.send() only supports dict CDP.
            try:
                _ = await _dom_get_root_node_id_obj_nodriver(page, uc)
                use_nodriver = True
            except Exception:
                _LOG.debug("nodriver probe failed in wait_for_selector, using dict CDP", exc_info=True)
                use_nodriver = False
        except Exception:
            _LOG.debug("nodriver import failed in wait_for_selector", exc_info=True)
            uc = None
            use_nodriver = False

        root_id: Any = None
        within_id: Any = None
        last_refresh = 0.0
        while True:
            now = loop.time()
            try:
                # Refresh the root node id occasionally (or after errors). This keeps polling fast
                # without spamming DOM.getDocument on every iteration.
                if (root_id is None) or ((now - last_refresh) >= float(refresh_document_s)):
                    if use_nodriver and uc is not None:
                        root_id = await _dom_get_root_node_id_obj_nodriver(page, uc)
                    else:
                        root_id = await _dom_get_root_node_id_int_dict(page)
                    within_id = None
                    last_refresh = now

                query_root = root_id
                found: Any = None

                if within_selector:
                    # Re-resolve the scope selector whenever it is missing/unmatched.
                    if not within_id:
                        if use_nodriver and uc is not None:
                            within_id = await _dom_query_selector_nodriver(page, uc, query_root, within_selector)
                        else:
                            within_id = await _dom_query_selector_int_dict(page, int(query_root), within_selector)

                        if not within_id:
                            within_id = None
                            found = None
                        else:
                            query_root = within_id

                    if within_id:
                        query_root = within_id

                if query_root:
                    if use_nodriver and uc is not None:
                        found = await _dom_query_selector_nodriver(page, uc, query_root, selector)
                    else:
                        found = await _dom_query_selector_int_dict(page, int(query_root), selector)

                if found:
                    return
            except Exception as e:
                # Not found yet (or transient DOM state); keep polling until timeout.
                last_exc = e
                # If the document changed under us, the cached nodeIds can become stale.
                root_id = None
                within_id = None

            if now >= deadline:
                if within_selector:
                    raise TimeoutError(
                        f"Timed out waiting for selector: {selector} within {within_selector}"
                    ) from last_exc
                raise TimeoutError(f"Timed out waiting for selector: {selector}") from last_exc

            await asyncio.sleep(poll)
            if poll > 0:
                # Deterministic backoff to reduce CDP churn when elements take time to appear.
                poll = min(max_poll, poll * 1.5)

    if hasattr(page, "wait_for_selector"):
        await page.wait_for_selector(selector, timeout=timeout_s)
        return

    if hasattr(page, "wait_for"):
        await page.wait_for(selector, timeout=timeout_s)
        return

    raise AttributeError("page has no wait_for_selector, send, or wait_for")


async def dom_get_outer_html(page: Any, node_id: int) -> str:
    if not hasattr(page, "send"):
        raise AttributeError("page has no send() for CDP DOM outerHTML")

    # Prefer nodriver's generated CDP commands if available (page.send usually expects these).
    uc = None
    try:
        import nodriver as uc  # type: ignore[assignment]
    except Exception:
        _LOG.debug("nodriver import failed in dom_get_outer_html", exc_info=True)
        uc = None

    resp: Any = None
    nodriver_exc: Exception | None = None
    if uc is not None:
        try:
            fn = getattr(getattr(getattr(uc, "cdp", None), "dom", None), "get_outer_html", None)
            if callable(fn):
                try:
                    resp = await page.send(fn(node_id))
                except TypeError:
                    resp = await page.send(fn(node_id=node_id))
        except Exception as e:
            nodriver_exc = e
            resp = None

    if resp is None:
        try:
            resp = await _send_dict(page, "DOM.getOuterHTML", {"nodeId": int(node_id)})
        except Exception:
            if nodriver_exc is not None:
                raise nodriver_exc
            raise

    if isinstance(resp, dict):
        v = resp.get("outerHTML") or resp.get("outer_html")
        if isinstance(v, str):
            return v
        # Some stacks might already return a string-ish value.
        return "" if v is None else str(v)

    v = getattr(resp, "outer_html", None) or getattr(resp, "outerHTML", None)
    if isinstance(v, str):
        return v
    return "" if resp is None else str(resp)


_WS_RE = re.compile(r"\s+")


def html_to_text(html: str) -> str:
    """
    Best-effort HTML -> textContent-ish string.

    This intentionally does not require Runtime evaluation/innerText.
    """
    # Prefer BeautifulSoup when available (optional dependency).
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(str(html), "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            try:
                tag.decompose()
            except Exception:
                _LOG.debug("tag.decompose() failed", exc_info=True)
        txt = soup.get_text(" ", strip=True)
        return str(txt or "").strip()
    except Exception:
        _LOG.debug("BeautifulSoup html_to_text failed, falling back to HTMLParser", exc_info=True)

    class _Extractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self._ignore_depth = 0

        def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
            if tag in {"script", "style"}:
                self._ignore_depth += 1

        def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
            if tag in {"script", "style"} and self._ignore_depth > 0:
                self._ignore_depth -= 1

        def handle_data(self, data: str) -> None:
            if self._ignore_depth:
                return
            if data:
                self.parts.append(data)

    p = _Extractor()
    p.feed(str(html))
    txt = _WS_RE.sub(" ", " ".join(p.parts)).strip()
    return txt


async def selector_text_content(page: Any, selector: str, *, within_selector: str | None = None) -> str:
    node_id = await dom_query_selector_node_id(page, selector, within_selector=within_selector)
    if not node_id:
        if within_selector:
            raise RuntimeError(f"DOM.querySelector returned no nodeId for selector: {selector} within {within_selector}")
        raise RuntimeError(f"DOM.querySelector returned no nodeId for selector: {selector}")

    html = await dom_get_outer_html(page, node_id)
    return html_to_text(html)


async def select(page: Any, selector: str) -> Any:
    """
    Wrapper around `page.select` that normalizes potential return shapes.

    Some driver APIs return a single element, while others may return a list of
    elements for a selector. We normalize to a single element handle (the first)
    or `None` if no element was found.
    """
    res = await page.select(selector)
    return normalize_element(res)


def normalize_element(res: Any) -> Any:
    if res is None:
        return None
    if isinstance(res, (list, tuple)):
        return res[0] if res else None
    return res


async def element_viewport_center(element: Any) -> ViewportPoint:
    # Prefer a bounding box if available.
    bb = getattr(element, "bounding_box", None)
    if bb is not None:
        try:
            box = bb() if callable(bb) else bb
            if inspect.isawaitable(box):
                box = await box

            if box is not None:
                if isinstance(box, dict):
                    x, y, w, h = box["x"], box["y"], box["width"], box["height"]
                else:
                    x, y, w, h = box.x, box.y, box.width, box.height
                cx, cy = rect_center(float(x), float(y), float(w), float(h))
                return ViewportPoint(cx, cy)
        except Exception:
            # If bounding box retrieval is unsupported for this element/driver, fall back to quads.
            _LOG.debug("bounding_box retrieval failed, falling back to quads", exc_info=True)

    # Fall back to quads if present.
    quads = None
    for name in ("quads", "content_quads", "get_content_quads"):
        quads = getattr(element, name, None)
        if quads is not None:
            break
    if quads is None:
        raise AttributeError("element has no usable bounding box or quads")

    if callable(quads):
        quads = quads()
    if inspect.isawaitable(quads):
        quads = await quads
    if not quads:
        raise ValueError("element.quads is empty")

    q0 = quads[0]
    cx, cy = quad_center([float(v) for v in q0])
    return ViewportPoint(cx, cy)


async def maybe_maximize(browser: Any) -> None:
    # Coordinate math is more consistent if the window is normalized/maximized.
    try:
        tab = getattr(browser, "main_tab", None)
        if tab is not None:
            fn = getattr(tab, "maximize", None)
            if callable(fn):
                res = fn()
                if inspect.isawaitable(res):
                    await res
                return

        fn = getattr(browser, "maximize", None)
        if callable(fn):
            res = fn()
            if inspect.isawaitable(res):
                await res
    except Exception:
        _LOG.debug("maybe_maximize failed", exc_info=True)
        return


async def maybe_bring_to_front(browser: Any) -> None:
    try:
        fn = getattr(browser, "bring_to_front", None)
        if callable(fn):
            res = fn()
            if inspect.isawaitable(res):
                await res
            return

        tab = getattr(browser, "main_tab", None)
        if tab is not None:
            fn = getattr(tab, "bring_to_front", None)
            if callable(fn):
                res = fn()
                if inspect.isawaitable(res):
                    await res
    except Exception:
        _LOG.debug("maybe_bring_to_front failed", exc_info=True)
        return
