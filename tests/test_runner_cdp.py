import asyncio
import os
import sys
import types
from pathlib import Path

import pytest

from spec2_hybrid.geometry import Noise
from spec2_hybrid.os_input import MouseProfile, TypingProfile
from spec2_hybrid.runner import FlowRunner, RunConfig


def _base_config(**overrides):
    cfg = RunConfig(
        url="",
        selector="#x",
        text="hi",
        press_enter=False,
        dry_run=True,
        timeout_s=1.0,
        browser_path=None,
        browser_channel="stable",
        download_browser=False,
        sandbox=False,
        browser_cache_dir=None,
        cdp_host=None,
        cdp_port=None,
        offset_x=0.0,
        offset_y=0.0,
        noise=Noise(x_px=0, y_px=0),
        mouse=MouseProfile(min_move_duration_s=0.0, max_move_duration_s=0.0),
        typing=TypingProfile(min_delay_s=0.0, max_delay_s=0.0),
        real_profile=None,
        shim_profile=None,
    )
    return cfg.__class__(**{**cfg.__dict__, **overrides})


def test_runner_uses_cdp_host_port(monkeypatch):
    calls = []

    async def fake_start(**kwargs):
        calls.append(kwargs)

        class _B:
            async def stop(self):
                return None

        return _B()

    fake_nodriver = types.SimpleNamespace(start=fake_start)
    monkeypatch.setitem(sys.modules, "nodriver", fake_nodriver)

    # Ensure we do not try to resolve or launch a local browser.
    import spec2_hybrid.runner as runner_mod

    def _boom(*args, **kwargs):
        raise AssertionError("resolve_browser_executable_path should not be called when using --cdp-*")

    monkeypatch.setattr(runner_mod, "resolve_browser_executable_path", _boom)

    async def _no_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(runner_mod.asyncio, "to_thread", _no_thread)

    cfg = _base_config(cdp_host="127.0.0.1", cdp_port=9222, dry_run=True)
    asyncio.run(FlowRunner(cfg).start())
    assert calls == [{"host": "127.0.0.1", "port": 9222}]


def test_runner_dry_run_no_display_goes_headless(monkeypatch):
    calls = []

    async def fake_start(**kwargs):
        calls.append(kwargs)

        class _B:
            async def stop(self):
                return None

        return _B()

    fake_nodriver = types.SimpleNamespace(start=fake_start)
    monkeypatch.setitem(sys.modules, "nodriver", fake_nodriver)

    import spec2_hybrid.runner as runner_mod

    async def _no_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    # Avoid relying on thread scheduling in unit tests.
    monkeypatch.setattr(runner_mod.asyncio, "to_thread", _no_thread)
    monkeypatch.setattr(runner_mod, "resolve_browser_executable_path", lambda **_: Path("/bin/true"))

    monkeypatch.setenv("DISPLAY", "")
    monkeypatch.setenv("WAYLAND_DISPLAY", "")

    cfg = _base_config(dry_run=True)
    asyncio.run(FlowRunner(cfg).start())
    assert calls
    assert calls[0].get("headless") is True


def test_runner_no_dry_run_no_display_errors(monkeypatch):
    fake_nodriver = types.SimpleNamespace(start=lambda **kwargs: None)
    monkeypatch.setitem(sys.modules, "nodriver", fake_nodriver)

    monkeypatch.setenv("DISPLAY", "")
    monkeypatch.setenv("WAYLAND_DISPLAY", "")

    cfg = _base_config(dry_run=False)
    with pytest.raises(RuntimeError, match="No GUI display detected"):
        asyncio.run(FlowRunner(cfg).start())
