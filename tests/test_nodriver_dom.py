import asyncio

from spec2_hybrid.nodriver_dom import (
    ViewportPoint,
    element_viewport_center,
    maybe_maximize,
    normalize_element,
    select,
    selector_viewport_center,
)


def test_normalize_element_list_tuple_none():
    assert normalize_element(None) is None
    assert normalize_element([]) is None
    assert normalize_element(()) is None
    assert normalize_element([1, 2]) == 1
    assert normalize_element(("a", "b")) == "a"
    assert normalize_element({"x": 1}) == {"x": 1}


def test_select_normalizes_list_result():
    class Page:
        async def select(self, selector: str):
            assert selector == "div"
            return ["el1", "el2"]

    assert asyncio.run(select(Page(), "div")) == "el1"


def test_element_viewport_center_falls_back_when_bounding_box_none():
    class El:
        # Some driver element types expose a "bounding_box" attribute that may be None.
        bounding_box = None

        async def quads(self):
            # A single quad for a 10x10 box at origin.
            return [[0, 0, 10, 0, 10, 10, 0, 10]]

    assert asyncio.run(element_viewport_center(El())) == ViewportPoint(5.0, 5.0)


def test_maybe_maximize_awaits_coroutine_methods():
    calls = []

    class Tab:
        async def maximize(self):
            calls.append("max")

    class Browser:
        main_tab = Tab()

    asyncio.run(maybe_maximize(Browser()))
    assert calls == ["max"]


def test_selector_viewport_center_uses_dom_box_model():
    class Page:
        async def send(self, msg):
            m = msg.get("method")
            if m == "DOM.enable":
                return {}
            if m == "DOM.getDocument":
                return {"root": {"nodeId": 1}}
            if m == "DOM.querySelector":
                assert msg["params"]["selector"] == "#x"
                return {"nodeId": 2}
            if m == "DOM.getBoxModel":
                # 0,0 to 10,10 box
                return {"model": {"content": [0, 0, 10, 0, 10, 10, 0, 10]}}
            if m == "Page.getLayoutMetrics":
                return {"visualViewport": {"pageX": 0, "pageY": 0}}
            raise AssertionError(f"unexpected CDP method: {m}")

    assert asyncio.run(selector_viewport_center(Page(), "#x")) == ViewportPoint(5.0, 5.0)


def test_wait_for_selector_prefers_cdp_polling_over_wait_for():
    calls = []

    class Page:
        async def send(self, msg):
            m = msg.get("method")
            calls.append(m)
            if m == "DOM.enable":
                return {}
            if m == "DOM.getDocument":
                return {"root": {"nodeId": 1}}
            if m == "DOM.querySelector":
                return {"nodeId": 2}
            raise AssertionError(f"unexpected CDP method: {m}")

        async def wait_for(self, selector: str, timeout: float):
            raise AssertionError("wait_for should not be called when send() is available")

    from spec2_hybrid.nodriver_dom import wait_for_selector

    asyncio.run(wait_for_selector(Page(), "#x", timeout_s=0.1))
    assert "DOM.querySelector" in calls

