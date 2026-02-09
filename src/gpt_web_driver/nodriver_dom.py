from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from .geometry import quad_center, rect_center


@dataclass(frozen=True)
class ViewportPoint:
    x: float
    y: float


def _quad_center_xy(quad: list[float]) -> tuple[float, float]:
    # quad is [x1,y1,x2,y2,x3,y3,x4,y4]
    xs = quad[0::2]
    ys = quad[1::2]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


async def selector_viewport_center(page: Any, selector: str) -> ViewportPoint:
    """
    DOM-only fallback for getting an element's viewport center.

    This avoids Runtime.evaluate (which we disable in stealth_init) by using
    DOM.getDocument/querySelector/getBoxModel via `page.send`.
    """
    if not hasattr(page, "send"):
        raise AttributeError("page has no send() for CDP DOM fallback")

    node_id = await dom_query_selector_node_id(page, selector)
    if not node_id:
        raise RuntimeError(f"DOM.querySelector returned no nodeId for selector: {selector}")

    # Prefer nodriver's generated CDP commands if available (page.send usually expects these).
    uc = None
    try:
        import nodriver as uc  # type: ignore[assignment]
    except Exception:
        uc = None

    def _maybe_dict(obj: Any) -> dict:
        return obj if isinstance(obj, dict) else {}

    async def _send_dict(method: str, params: dict[str, Any] | None = None) -> Any:
        msg: dict[str, Any] = {"method": method}
        if params:
            msg["params"] = params
        return await page.send(msg)

    bm: Any
    nodriver_exc: Exception | None = None
    if uc is not None:
        fn = getattr(getattr(uc, "cdp", None), "dom", None)
        fn = getattr(fn, "get_box_model", None) if fn is not None else None
        if callable(fn):
            try:
                bm = await page.send(fn(node_id))  # prefer NodeId (has to_json)
            except TypeError:
                bm = await page.send(fn(node_id=node_id))
            except Exception as e:
                # Could be a non-nodriver page.send() implementation. Fall back to dict CDP.
                nodriver_exc = e
                bm = None
        else:
            bm = None
    else:
        bm = None

    if bm is None:
        try:
            bm = await _send_dict("DOM.getBoxModel", {"nodeId": int(node_id)})
        except Exception:
            # If this is a real nodriver Tab, dict CDP won't work; surface the original error.
            if nodriver_exc is not None:
                raise nodriver_exc
            raise

    quad: Any = None
    if isinstance(bm, dict):
        model = (bm.get("model") or {}) if isinstance(bm.get("model"), dict) else {}
        quad = model.get("content") or model.get("border") or model.get("margin")
    else:
        # nodriver returns a BoxModel dataclass with Quad(list) members.
        for name in ("content", "border", "margin"):
            if hasattr(bm, name):
                quad = getattr(bm, name)
                if quad:
                    break

    if not quad:
        raise RuntimeError(f"DOM.getBoxModel returned no quad for selector: {selector}")

    quad_f = [float(v) for v in quad]
    cx, cy = _quad_center_xy(quad_f)

    # DOM.getBoxModel coordinates are in page coordinates; convert to viewport coordinates
    # by subtracting the visual viewport origin when available.
    try:
        metrics: Any = None
        if uc is not None:
            try:
                p = getattr(getattr(uc, "cdp", None), "page", None)
                fnm = getattr(p, "get_layout_metrics", None) if p is not None else None
                if callable(fnm):
                    metrics = await page.send(fnm())
            except Exception:
                metrics = None

        if metrics is None:
            metrics = await _send_dict("Page.getLayoutMetrics")

        # nodriver returns a 6-tuple; dict-based CDP stacks return a dict.
        vv: Any = {}
        if isinstance(metrics, tuple) and len(metrics) >= 2:
            vv = metrics[1]
        elif isinstance(metrics, dict):
            vv = metrics.get("visualViewport") or {}

        page_x = 0.0
        page_y = 0.0
        if isinstance(vv, dict):
            page_x = float(vv.get("pageX") or 0.0)
            page_y = float(vv.get("pageY") or 0.0)
        else:
            page_x = float(getattr(vv, "page_x", 0.0) or 0.0)
            page_y = float(getattr(vv, "page_y", 0.0) or 0.0)
        cx -= page_x
        cy -= page_y
    except Exception:
        pass
    return ViewportPoint(cx, cy)


async def dom_query_selector_node_id(page: Any, selector: str) -> int:
    """
    CDP DOM querySelector that returns a nodeId (0 if not found).
    """
    if not hasattr(page, "send"):
        raise AttributeError("page has no send() for CDP DOM query")

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

    async def _send(method: str, params: dict[str, Any] | None = None) -> Any:
        msg: dict[str, Any] = {"method": method}
        if params:
            msg["params"] = params
        return await page.send(msg)

    # Prefer nodriver's generated CDP commands if available (page.send usually expects these).
    uc = None
    try:
        import nodriver as uc  # type: ignore[assignment]
    except Exception:
        uc = None

    if uc is not None:
        try:
            # Best-effort; ignore if the domain is already enabled or API differs.
            try:
                await page.send(uc.cdp.dom.enable())
            except Exception:
                pass

            # Match nodriver's own usage: get_document(-1, True) for stability across frames/updates.
            try:
                doc = await page.send(uc.cdp.dom.get_document(-1, True))
            except TypeError:
                doc = await page.send(uc.cdp.dom.get_document())

            # nodriver returns a Node object (node_id is a NodeId which has to_json()).
            root_id_obj = _get(doc, "node_id", "nodeId")
            if root_id_obj is None:
                # Fallback to dict-ish shape if some driver returns {"root": {"nodeId": ...}}.
                root = _get(doc, "root") or doc
                root_id_obj = _get(root, "node_id", "nodeId") or _node_id_from(root)

            if not root_id_obj:
                return 0

            q_resp = await page.send(uc.cdp.dom.query_selector(root_id_obj, selector))
            # nodriver returns a NodeId (int subclass) which also supports .to_json().
            return q_resp if q_resp else 0
        except Exception:
            # If this is not a real nodriver Tab (e.g., unit test fake), fall back to dict CDP.
            pass

    # Generic CDP fallback (for test fakes or other drivers that accept dict messages).
    try:
        await _send("DOM.enable")
    except Exception:
        pass

    doc = await _send("DOM.getDocument", {"depth": 1, "pierce": True})
    root = _get(doc, "root") or {}
    root_id = _node_id_from(root)
    if not root_id:
        return 0

    q = await _send("DOM.querySelector", {"nodeId": int(root_id), "selector": selector})
    return _node_id_from(q)


async def wait_for_selector(page: Any, selector: str, *, timeout_s: float) -> None:
    # Prefer a CDP DOM polling loop over driver-provided wait_for(), since some
    # stacks cache a stale document nodeId across navigations (observed in nodriver).
    if hasattr(page, "send"):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(timeout_s)
        last_exc: Exception | None = None
        while True:
            try:
                if await dom_query_selector_node_id(page, selector):
                    return
            except Exception as e:
                # Not found yet (or transient DOM state); keep polling until timeout.
                last_exc = e

            if loop.time() >= deadline:
                raise TimeoutError(f"Timed out waiting for selector: {selector}") from last_exc
            await asyncio.sleep(0.05)

    if hasattr(page, "wait_for_selector"):
        await page.wait_for_selector(selector, timeout=timeout_s)
        return

    if hasattr(page, "wait_for"):
        await page.wait_for(selector, timeout=timeout_s)
        return

    raise AttributeError("page has no wait_for_selector, send, or wait_for")


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
            pass

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
        return
