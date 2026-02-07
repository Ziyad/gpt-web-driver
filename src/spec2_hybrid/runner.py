from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .browser import resolve_browser_executable_path
from .demo_server import serve_directory
from .geometry import Noise, apply_noise, viewport_to_screen
from .nodriver_dom import (
    ViewportPoint,
    element_viewport_center,
    maybe_bring_to_front,
    maybe_maximize,
    select,
    wait_for_selector,
)
from .os_input import MouseProfile, OsInput, TypingProfile
from .profile import ProfileConfig, ensure_profile
from .stealth import stealth_init


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

        if self._cfg.real_profile and self._cfg.shim_profile:
            ensure_profile(
                ProfileConfig(
                    real_profile_dir=self._cfg.real_profile,
                    shim_profile_dir=self._cfg.shim_profile,
                )
            )

        import nodriver as uc  # local import: unit tests run without nodriver installed

        no_linux_display = False
        if sys.platform.startswith("linux"):
            no_linux_display = (os.environ.get("DISPLAY") in (None, "")) and (
                os.environ.get("WAYLAND_DISPLAY") in (None, "")
            )

        # This project is "headed" by design when doing OS-level input, but in plain
        # WSL (no WSLg/X11) we still want `--dry-run` to be runnable end-to-end.
        if (not self._cfg.dry_run) and no_linux_display:
            raise RuntimeError(
                "No GUI display detected (DISPLAY/WAYLAND_DISPLAY unset). "
                "Run under WSLg/X11 or use --dry-run."
            )

        # Connect to an existing debuggable Chrome instead of launching a local browser.
        if self._cfg.cdp_host and (self._cfg.cdp_port is not None):
            kwargs = {"host": str(self._cfg.cdp_host), "port": int(self._cfg.cdp_port)}
        else:
            kwargs = {"headless": bool(self._cfg.dry_run and no_linux_display)}
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
        maybe_maximize(self._browser)

    async def close(self) -> None:
        if self._browser is None:
            return
        try:
            await self._browser.stop()
        except Exception:
            try:
                self._browser.stop()
            except Exception:
                pass
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
        el = await select(self._page, selector)
        if not el:
            raise RuntimeError(f"Element not found for selector: {selector}")
        return await element_viewport_center(el)

    async def interact(self, *, selector: str, text: Optional[str]) -> None:
        assert self._browser is not None
        if self._os is None:
            self._os = OsInput(dry_run=self._cfg.dry_run)

        pt = await self.locate_point(selector)
        sx, sy = viewport_to_screen(pt.x, pt.y, offset_x=self._cfg.offset_x, offset_y=self._cfg.offset_y)
        fx, fy = apply_noise(sx, sy, noise=self._cfg.noise)

        maybe_bring_to_front(self._browser)
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
