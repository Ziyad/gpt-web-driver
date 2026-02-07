from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

from .geometry import quad_center, rect_center


@dataclass(frozen=True)
class ViewportPoint:
    x: float
    y: float


async def wait_for_selector(page: Any, selector: str, *, timeout_s: float) -> None:
    if hasattr(page, "wait_for_selector"):
        await page.wait_for_selector(selector, timeout=timeout_s)
        return
    if hasattr(page, "wait_for"):
        await page.wait_for(selector, timeout=timeout_s)
        return
    raise AttributeError("page has no wait_for_selector or wait_for")


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
    if hasattr(element, "bounding_box"):
        box = await element.bounding_box()
        if isinstance(box, dict):
            x, y, w, h = box["x"], box["y"], box["width"], box["height"]
        else:
            x, y, w, h = box.x, box.y, box.width, box.height
        cx, cy = rect_center(float(x), float(y), float(w), float(h))
        return ViewportPoint(cx, cy)

    # Fall back to quads if present.
    quads = getattr(element, "quads", None)
    if quads is None:
        raise AttributeError("element has no bounding_box() or quads")

    if callable(quads):
        quads = await quads()
    if not quads:
        raise ValueError("element.quads is empty")

    q0 = quads[0]
    cx, cy = quad_center([float(v) for v in q0])
    return ViewportPoint(cx, cy)


def maybe_maximize(browser: Any) -> None:
    # Coordinate math is more consistent if the window is normalized/maximized.
    try:
        tab = getattr(browser, "main_tab", None)
        if tab is not None and hasattr(tab, "maximize"):
            tab.maximize()
            return
        if hasattr(browser, "maximize"):
            browser.maximize()
    except Exception:
        return


def maybe_bring_to_front(browser: Any) -> None:
    try:
        if hasattr(browser, "bring_to_front"):
            browser.bring_to_front()
            return
        tab = getattr(browser, "main_tab", None)
        if tab is not None and hasattr(tab, "bring_to_front"):
            tab.bring_to_front()
    except Exception:
        return
