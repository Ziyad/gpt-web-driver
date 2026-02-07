import asyncio

from spec2_hybrid.nodriver_dom import normalize_element, select


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

