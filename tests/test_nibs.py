from __future__ import annotations

import asyncio
import types

import pytest

from gpt_web_driver.nodriver_dom import ViewportPoint


def test_nibs_chat_completion_does_not_mask_errors_with_cancelled_error(monkeypatch):
    import gpt_web_driver.nibs as nibs

    class FakeOsInput:
        def position(self) -> tuple[float, float]:
            return (0.0, 0.0)

        def click(self) -> None:
            return None

        def scroll(self, clicks: int) -> None:
            return None

        def press(self, key: str) -> None:
            return None

    class FakeRunner:
        def __init__(self) -> None:
            self.page = object()
            self.browser = object()
            self._os = FakeOsInput()
            self.config = types.SimpleNamespace(
                scale_x=1.0,
                scale_y=1.0,
                offset_x=0.0,
                offset_y=0.0,
                noise=None,
                pre_interact_delay_s=0.0,
                post_click_delay_s=0.0,
            )

        def os_input(self) -> FakeOsInput:
            return self._os

    async def fake_last_assistant_message_text(*_a, **_k):
        return None

    async def fake_wait_for_selector(*_a, **_k):
        return None

    async def fake_selector_viewport_gaussian_point(*_a, **_k):
        return ViewportPoint(1.0, 2.0)

    async def fake_maybe_bring_to_front(*_a, **_k):
        return None

    def fake_viewport_to_screen(x: float, y: float, **_k):
        return (x, y)

    def fake_apply_noise(x: float, y: float, **_k):
        return (x, y)

    class FakeMouse:
        def __init__(self, *_a, **_k) -> None:
            return None

        async def move_to(self, *_a, **_k) -> None:
            return None

    class FakeHybrid:
        def __init__(self, *_a, **_k) -> None:
            return None

        async def smart_enter(self, _text: str) -> None:
            return None

    async def fake_wait_for_assistant_reply(*_a, on_poll=None, **_k) -> str:
        # Wait long enough to trigger a flick via on_poll(), then fail.
        if on_poll is not None:
            await asyncio.sleep(0.25)
            on_poll()
            await asyncio.sleep(0)
        raise RuntimeError("boom")

    monkeypatch.setattr(nibs, "last_assistant_message_text", fake_last_assistant_message_text)
    monkeypatch.setattr(nibs, "wait_for_selector", fake_wait_for_selector)
    monkeypatch.setattr(nibs, "selector_viewport_gaussian_point", fake_selector_viewport_gaussian_point)
    monkeypatch.setattr(nibs, "maybe_bring_to_front", fake_maybe_bring_to_front)
    monkeypatch.setattr(nibs, "viewport_to_screen", fake_viewport_to_screen)
    monkeypatch.setattr(nibs, "apply_noise", fake_apply_noise)
    monkeypatch.setattr(nibs, "NeuromotorMouse", FakeMouse)
    monkeypatch.setattr(nibs, "HybridInput", FakeHybrid)
    monkeypatch.setattr(nibs, "wait_for_assistant_reply", fake_wait_for_assistant_reply)

    cfg = nibs.NibsConfig(run=types.SimpleNamespace(seed=15), ui=nibs.ChatUIConfig(url="https://example.com/"))
    s = nibs.NibsSession(cfg)
    s._runner = FakeRunner()

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(s.chat_completion("hi"))

