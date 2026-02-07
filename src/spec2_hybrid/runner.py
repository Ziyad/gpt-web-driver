from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from .browser import resolve_browser_executable_path
from .demo_server import serve_directory
from .geometry import Noise, apply_noise, viewport_to_screen
from .nodriver_dom import (
    ViewportPoint,
    element_viewport_center,
    maybe_bring_to_front,
    maybe_maximize,
    select,
    selector_viewport_center,
    wait_for_selector,
)
from .os_input import MouseProfile, OsInput, TypingProfile
from .profile import ProfileConfig, ensure_profile
from .stealth import stealth_init


def _no_gui_display(env: Mapping[str, str] = os.environ, *, sys_platform: str = sys.platform) -> bool:
    """
    Best-effort detection of "no GUI display available".

    - Linux: use DISPLAY/WAYLAND_DISPLAY (common for X11/Wayland).
    - Non-Linux: do not assume these vars exist; only honor them if explicitly present.
      This lets tests force a "no display" condition on Windows/macOS without breaking
      normal GUI sessions where DISPLAY is typically unset.
    """
    display_keys_present = ("DISPLAY" in env) or ("WAYLAND_DISPLAY" in env)

    if sys_platform.startswith("linux") or display_keys_present:
        return (env.get("DISPLAY") in (None, "")) and (env.get("WAYLAND_DISPLAY") in (None, ""))

    return False


@dataclass(frozen=True)
class RunConfig:
    url: str
    selector: str
    text: Optional[str]
    press_enter: bool
    dry_run: bool
    timeout_s: float
    browser_path: Optional[Path]
    browser_channel: str
    download_browser: bool
    sandbox: bool
    browser_cache_dir: Optional[Path]
    cdp_host: Optional[str]
    cdp_port: Optional[int]
    offset_x: float
    offset_y: float
    noise: Noise
    mouse: MouseProfile
    typing: TypingProfile
    real_profile: Optional[Path]
    shim_profile: Optional[Path]


class FlowRunner:
    def __init__(self, config: RunConfig) -> None:
        self._cfg = config
        self._browser: Any = None
        self._page: Any = None
        # Lazily created to avoid importing pyautogui in environments without a GUI
        # (especially when we will fail fast before interaction).
        self._os: Optional[OsInput] = None

    async def __aenter__(self) -> "FlowRunner":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        if self._browser is not None:
            return

        no_display = _no_gui_display()

        if self._cfg.real_profile and self._cfg.shim_profile:
            ensure_profile(
                ProfileConfig(
                    real_profile_dir=self._cfg.real_profile,
                    shim_profile_dir=self._cfg.shim_profile,
                )
            )

        # This project is "headed" by design when doing OS-level input, but in plain
        # WSL (no WSLg/X11) we still want `--dry-run` to be runnable end-to-end.
        if (not self._cfg.dry_run) and no_display:
            raise RuntimeError(
                "No GUI display detected. Run in an interactive GUI session, or use --dry-run."
            )

        import nodriver as uc  # local import: unit tests run without nodriver installed

        # Connect to an existing debuggable Chrome instead of launching a local browser.
        if self._cfg.cdp_host and (self._cfg.cdp_port is not None):
            kwargs = {"host": str(self._cfg.cdp_host), "port": int(self._cfg.cdp_port)}
        else:
            kwargs = {"headless": bool(self._cfg.dry_run and no_display)}
            if self._cfg.shim_profile:
                kwargs["user_data_dir"] = str(self._cfg.shim_profile)

            browser_exe = await asyncio.to_thread(
                resolve_browser_executable_path,
                explicit_path=self._cfg.browser_path,
                download=bool(self._cfg.download_browser),
                channel=str(self._cfg.browser_channel),
                cache_dir=self._cfg.browser_cache_dir,
            )
            kwargs["browser_executable_path"] = str(browser_exe)
            kwargs["sandbox"] = bool(self._cfg.sandbox)

        self._browser = await uc.start(**kwargs)
        await maybe_maximize(self._browser)

    async def close(self) -> None:
        if self._browser is None:
            return
        b = self._browser

        # nodriver's Browser.stop() is synchronous and does not await process transport cleanup.
        # On Windows this can lead to noisy "unclosed transport" ResourceWarnings at interpreter exit.
        proc = getattr(b, "_process", None)
        conn = getattr(b, "connection", None)

        with contextlib.suppress(Exception):
            stop = getattr(b, "stop", None)
            if callable(stop):
                stop()

        # Ensure websocket listener task is cancelled and socket closed.
        with contextlib.suppress(Exception):
            disc = getattr(conn, "disconnect", None)
            if callable(disc):
                await asyncio.wait_for(disc(), timeout=2.0)

        # Best-effort cleanup for the spawned browser subprocess transport.
        if proc is not None:
            with contextlib.suppress(Exception):
                if getattr(proc, "returncode", None) is None:
                    proc.terminate()

            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=2.0)

            # If still running, escalate.
            if getattr(proc, "returncode", None) is None:
                with contextlib.suppress(Exception):
                    proc.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=2.0)

            # Close stdin writer if present.
            with contextlib.suppress(Exception):
                if proc.stdin is not None:
                    proc.stdin.close()
                    with contextlib.suppress(Exception):
                        await proc.stdin.wait_closed()

            # Close underlying transport to avoid ResourceWarnings at GC time.
            with contextlib.suppress(Exception):
                transport = getattr(proc, "_transport", None)
                if transport is not None:
                    transport.close()

        # Let any pending disconnect callbacks flush before loop teardown.
        with contextlib.suppress(Exception):
            await asyncio.sleep(0)

        self._browser = None
        self._page = None

    async def navigate(self, url: str) -> Any:
        assert self._browser is not None
        self._page = await self._browser.get(url)
        await stealth_init(self._page)
        return self._page

    async def locate_point(self, selector: str) -> ViewportPoint:
        assert self._page is not None
        await wait_for_selector(self._page, selector, timeout_s=self._cfg.timeout_s)
        try:
            el = await select(self._page, selector)
        except Exception:
            # Some driver versions have flaky element-handle selection; fall back to CDP.
            return await selector_viewport_center(self._page, selector)

        if not el:
            # Last resort: try CDP directly (wait_for_selector should have ensured presence,
            # but driver APIs can still return None depending on implementation).
            return await selector_viewport_center(self._page, selector)

        try:
            return await element_viewport_center(el)
        except Exception:
            return await selector_viewport_center(self._page, selector)

    async def interact(self, *, selector: str, text: Optional[str]) -> None:
        assert self._browser is not None
        if self._os is None:
            self._os = OsInput(dry_run=self._cfg.dry_run)

        pt = await self.locate_point(selector)
        sx, sy = viewport_to_screen(pt.x, pt.y, offset_x=self._cfg.offset_x, offset_y=self._cfg.offset_y)
        fx, fy = apply_noise(sx, sy, noise=self._cfg.noise)

        await maybe_bring_to_front(self._browser)
        self._os.move_to(fx, fy, profile=self._cfg.mouse)
        self._os.click()

        if text:
            await asyncio.sleep(0.5)
            await self._os.human_type(text, profile=self._cfg.typing)
            if self._cfg.press_enter:
                self._os.press("enter")


def default_dry_run() -> bool:
    """
    Best-effort heuristic for default dry-run.

    - Linux: if neither X11 nor Wayland display env vars are set, assume no GUI.
    - macOS/Windows: do not key off DISPLAY (often unset even in GUI sessions).
    """
    override = os.environ.get("SPEC2_DRY_RUN")
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "y", "on"}

    import sys

    if sys.platform.startswith("linux"):
        return (os.environ.get("DISPLAY") in (None, "")) and (os.environ.get("WAYLAND_DISPLAY") in (None, ""))
    return False


async def run_single(config: RunConfig) -> None:
    async with FlowRunner(config) as runner:
        await runner.navigate(config.url)
        await runner.interact(selector=config.selector, text=config.text)


async def run_demo(config: RunConfig, *, repo_root: Path) -> None:
    server = serve_directory(repo_root)
    try:
        url = f"{server.base_url}/sample-body.html"
        async with FlowRunner(config) as runner:
            await runner.navigate(url)
            await runner.interact(selector=config.selector, text=config.text)
            # Show multi-step behavior in a single session by re-running an action.
            await runner.interact(selector=config.selector, text=config.text)
    finally:
        server.close()
