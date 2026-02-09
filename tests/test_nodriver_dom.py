import asyncio

from gpt_web_driver.nodriver_dom import (
    ViewportPoint,
    dom_get_outer_html,
    dom_query_selector_node_id,
    element_viewport_center,
    html_to_text,
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
            if m == "DOM.getDocument":
                assert msg.get("params", {}).get("depth") == 1
                assert msg.get("params", {}).get("pierce") is True
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
            if m == "DOM.getDocument":
                return {"root": {"nodeId": 1}}
            if m == "DOM.querySelector":
                return {"nodeId": 2}
            raise AssertionError(f"unexpected CDP method: {m}")

        async def wait_for(self, selector: str, timeout: float):
            raise AssertionError("wait_for should not be called when send() is available")

    from gpt_web_driver.nodriver_dom import wait_for_selector

    asyncio.run(wait_for_selector(Page(), "#x", timeout_s=0.1))
    assert calls == ["DOM.getDocument", "DOM.querySelector"]


def test_dom_query_selector_node_id_within_selector_scopes_query():
    calls: list[dict] = []

    class Page:
        async def send(self, msg):
            calls.append(msg)
            m = msg.get("method")
            if m == "DOM.getDocument":
                assert msg.get("params", {}).get("depth") == 1
                assert msg.get("params", {}).get("pierce") is True
                return {"root": {"nodeId": 1}}
            if m == "DOM.querySelector":
                sel = msg["params"]["selector"]
                if sel == "#root":
                    assert msg["params"]["nodeId"] == 1
                    return {"nodeId": 10}
                if sel == ".child":
                    assert msg["params"]["nodeId"] == 10
                    return {"nodeId": 11}
                raise AssertionError(f"unexpected selector: {sel}")
            raise AssertionError(f"unexpected CDP method: {m}")

    nid = asyncio.run(dom_query_selector_node_id(Page(), ".child", within_selector="#root"))
    assert nid == 11


def test_dom_get_outer_html_dict_cdp():
    class Page:
        async def send(self, msg):
            m = msg.get("method")
            if m == "DOM.getOuterHTML":
                assert msg["params"]["nodeId"] == 2
                return {"outerHTML": "<div>Hello <b>world</b></div>"}
            raise AssertionError(f"unexpected CDP method: {m}")

    assert asyncio.run(dom_get_outer_html(Page(), 2)) == "<div>Hello <b>world</b></div>"


def test_html_to_text_strips_tags_and_ignores_script_style():
    html = "<div> A <span>B</span> C <script>bad()</script><style>.x{}</style></div>"
    assert html_to_text(html) == "A B C"

