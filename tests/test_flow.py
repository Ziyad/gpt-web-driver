import asyncio

import pytest

import gpt_web_driver.flow as flow_mod
from gpt_web_driver.runner import RunConfig


def test_render_template_unknown_var_raises():
    with pytest.raises(flow_mod.FlowSpecError):
        flow_mod.render_template("hi {{missing}}", {"x": 1})


def test_run_flow_executes_steps_and_renders_result(monkeypatch):
    calls = []
    events = []

    class FakeRunner:
        def __init__(self, cfg, *, emit=None, include_text_in_events=False):
            self._emit = emit

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def navigate(self, url: str):
            calls.append(("navigate", url))

        async def click(self, selector: str, *, within_selector=None):
            calls.append(("click", selector, within_selector))

        async def type(
            self,
            selector: str,
            text: str,
            *,
            within_selector=None,
            click_first=True,
            press_enter=False,
            post_click_delay_s=None,
        ):
            calls.append(("type", selector, text, within_selector, click_first, press_enter, post_click_delay_s))

        async def wait_for_text(
            self,
            selector: str,
            *,
            contains: str,
            within_selector=None,
            timeout_s=None,
            poll_s=None,
        ) -> str:
            calls.append(("wait_for_text", selector, contains, within_selector, timeout_s, poll_s))
            return f"xx{contains}yy"

        async def extract_text(self, selector: str, *, within_selector=None, timeout_s=None) -> str:
            calls.append(("extract_text", selector, within_selector, timeout_s))
            return "EXTRACTED"

        async def wait_for_selector(self, selector: str, *, within_selector=None, timeout_s=None):
            calls.append(("wait_for_selector", selector, within_selector, timeout_s))

        async def press(self, key: str):
            calls.append(("press", key))

    monkeypatch.setattr(flow_mod, "FlowRunner", FakeRunner)

    def _emit(ev: dict):
        events.append(ev)

    cfg = RunConfig.defaults(url="about:blank", dry_run=True)
    spec = {
        "vars": {"q": "hi"},
        "steps": [
            {"action": "navigate", "url": "http://x/{{q}}"},
            {"action": "type", "selector": "#a", "text": "{{q}}", "press_enter": True},
            {"action": "wait_for_text", "selector": ".s", "contains": "OK", "into": "status"},
            {"action": "extract_text", "selector": "#out", "into": "result"},
        ],
        "result": "{{status}}/{{result}}",
    }

    res = asyncio.run(flow_mod.run_flow(cfg, spec, emit=_emit))
    assert res.value == "xxOKyy/EXTRACTED"
    assert calls == [
        ("navigate", "http://x/hi"),
        ("type", "#a", "hi", None, True, True, None),
        ("wait_for_text", ".s", "OK", None, None, None),
        ("extract_text", "#out", None, None),
    ]
    assert [e["event"] for e in events] == [
        "flow.step.start",
        "flow.step.end",
        "flow.step.start",
        "flow.step.end",
        "flow.step.start",
        "flow.step.end",
        "flow.step.start",
        "flow.step.end",
    ]


def test_run_flow_vars_override(monkeypatch):
    class FakeRunner:
        def __init__(self, cfg, *, emit=None, include_text_in_events=False):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def navigate(self, url: str):
            assert url == "http://x/OVR"

    monkeypatch.setattr(flow_mod, "FlowRunner", FakeRunner)
    cfg = RunConfig.defaults(url="about:blank", dry_run=True)
    spec = {"vars": {"q": "hi"}, "steps": [{"action": "navigate", "url": "http://x/{{q}}"}]}
    res = asyncio.run(flow_mod.run_flow(cfg, spec, vars={"q": "OVR"}))
    assert res.value == ""

