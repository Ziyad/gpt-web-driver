from __future__ import annotations

import asyncio
import contextlib
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Self

from .browser import resolve_browser_executable_path
from .demo_server import serve_directory
from .geometry import Noise, apply_noise, viewport_to_screen
from .nodriver_dom import (
    ViewportPoint,
    maybe_bring_to_front,
    maybe_maximize,
    selector_viewport_center,
    selector_text_content,
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


def _env_first(env: Mapping[str, str], *keys: str) -> Optional[str]:
    for k in keys:
        v = env.get(k)
        if v is not None:
            return v
    return None


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
    scale_x: float
    scale_y: float
    offset_x: float
    offset_y: float
    noise: Noise
    mouse: MouseProfile
    typing: TypingProfile
    real_profile: Optional[Path]
    shim_profile: Optional[Path]
    seed: Optional[int]
    pre_interact_delay_s: float
    post_click_delay_s: float

    @classmethod
    def defaults(
        cls,
        *,
        url: str,
        selector: str = "#prompt-textarea",
        text: str | None = "Hello, this is a test prompt.",
        press_enter: bool = True,
        dry_run: bool | None = None,
        timeout_s: float = 20.0,
        browser_path: Path | None = None,
        browser_channel: str | None = None,
        download_browser: bool | None = None,
        sandbox: bool | None = None,
        browser_cache_dir: Path | None = None,
        cdp_host: str | None = None,
        cdp_port: int | None = None,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        offset_x: float = 0.0,
        offset_y: float = 80.0,
        noise: Noise | None = None,
        mouse: MouseProfile | None = None,
        typing: TypingProfile | None = None,
        real_profile: Path | None = None,
        shim_profile: Path | None = None,
        seed: int | None = None,
        pre_interact_delay_s: float = 0.0,
        post_click_delay_s: float = 0.5,
    ) -> Self:
        """
        Create a RunConfig with CLI-like defaults.
        """
        from .browser import default_browser_channel, default_browser_sandbox, default_download_browser

        return cls(
            url=str(url),
            selector=str(selector),
            text=(str(text) if text is not None else None),
            press_enter=bool(press_enter),
            dry_run=default_dry_run() if dry_run is None else bool(dry_run),
            timeout_s=float(timeout_s),
            browser_path=browser_path,
            browser_channel=str(browser_channel or default_browser_channel()),
            download_browser=default_download_browser() if download_browser is None else bool(download_browser),
            sandbox=default_browser_sandbox() if sandbox is None else bool(sandbox),
            browser_cache_dir=browser_cache_dir,
            cdp_host=(str(cdp_host) if cdp_host else None),
            cdp_port=(int(cdp_port) if cdp_port is not None else None),
            scale_x=float(scale_x),
            scale_y=float(scale_y),
            offset_x=float(offset_x),
            offset_y=float(offset_y),
            noise=noise or Noise(x_px=12, y_px=5),
            mouse=mouse or MouseProfile(min_move_duration_s=0.2, max_move_duration_s=0.6),
            typing=typing or TypingProfile(min_delay_s=0.05, max_delay_s=0.15),
            real_profile=real_profile,
            shim_profile=shim_profile,
            seed=(int(seed) if seed is not None else None),
            pre_interact_delay_s=float(pre_interact_delay_s),
            post_click_delay_s=float(post_click_delay_s),
        )


class FlowRunner:
    def __init__(
        self,
        config: RunConfig,
        *,
        emit: Callable[[dict[str, Any]], None] | None = None,
        include_text_in_events: bool = False,
    ) -> None:
        self._cfg = config
        self._emit = emit
        self._include_text_in_events = bool(include_text_in_events)
        self._browser: Any = None
        self._page: Any = None
        # Lazily created to avoid importing pyautogui in environments without a GUI
        # (especially when we will fail fast before interaction).
        self._os: Optional[OsInput] = None
        self._noise_rng: random.Random | None = None
        self._os_rng: random.Random | None = None
        if self._cfg.seed is not None:
            # Use split RNGs so noise and OS timing remain deterministic but do not
            # influence each other based on call ordering.
            base = int(self._cfg.seed)
            self._noise_rng = random.Random(base ^ 0xC0FFEE)
            self._os_rng = random.Random(base ^ 0xBAD5EED)

    async def __aenter__(self) -> "FlowRunner":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        if self._browser is not None:
            return

        no_display = _no_gui_display()
        using_cdp = bool(self._cfg.cdp_host and (self._cfg.cdp_port is not None))

        if self._cfg.real_profile and self._cfg.shim_profile:
            ensure_profile(
                ProfileConfig(
                    real_profile_dir=self._cfg.real_profile,
                    shim_profile_dir=self._cfg.shim_profile,
                )
            )

        # OS-level input requires a GUI session. Also note: even in --dry-run, this project
        # keeps the browser headed by design. If you have no local display, connect to an
        # already-running headed Chrome via --cdp-host/--cdp-port.
        if no_display:
            if not self._cfg.dry_run:
                raise RuntimeError(
                    "No GUI display detected. OS-level input requires a GUI session. "
                    "Run in an interactive GUI session, or use --dry-run."
                )
            if not using_cdp:
                raise RuntimeError(
                    "No GUI display detected. --dry-run disables OS-level input, but the browser is still headed. "
                    "Run with a real/virtual display (e.g., X11/Wayland/WSLg/Xvfb), or connect to a headed Chrome via "
                    "--cdp-host/--cdp-port."
                )

        import nodriver as uc  # local import: unit tests run without nodriver installed

        # Connect to an existing debuggable Chrome instead of launching a local browser.
        if self._cfg.cdp_host and (self._cfg.cdp_port is not None):
            kwargs = {"host": str(self._cfg.cdp_host), "port": int(self._cfg.cdp_port)}
        else:
            kwargs = {"headless": False}
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
        if self._emit is not None:
            self._emit({"event": "navigate", "url": str(url)})
        self._page = await self._browser.get(url)
        await stealth_init(self._page)
        return self._page

    @property
    def browser(self) -> Any:
        return self._browser

    @property
    def page(self) -> Any:
        return self._page

    def os_input(self) -> OsInput:
        """
        Access the OS input layer for advanced workflows.
        """
        return self._ensure_os()

    @property
    def config(self) -> RunConfig:
        return self._cfg

    async def locate_point(self, selector: str, *, within_selector: str | None = None) -> ViewportPoint:
        assert self._page is not None
        await wait_for_selector(
            self._page,
            selector,
            within_selector=within_selector,
            timeout_s=self._cfg.timeout_s,
        )
        # Always use the CDP DOM path to avoid relying on driver-specific element-handle
        # behaviors (which may internally evaluate JS depending on implementation/version).
        return await selector_viewport_center(self._page, selector, within_selector=within_selector)

    def _ensure_os(self) -> OsInput:
        if self._os is None:
            assert self._browser is not None
            self._os = OsInput(
                dry_run=self._cfg.dry_run,
                rng=self._os_rng,
                emit=self._emit,
                include_text_in_events=self._include_text_in_events,
            )
        return self._os

    def _emit_point(
        self,
        *,
        action: str,
        selector: str,
        within_selector: str | None,
        pt: ViewportPoint,
        sx: float,
        sy: float,
        fx: float,
        fy: float,
    ) -> None:
        if self._emit is None:
            return
        ev: dict[str, Any] = {
            "event": "interact.point",
            "action": str(action),
            "selector": str(selector),
            "viewport_x": float(pt.x),
            "viewport_y": float(pt.y),
            "scale_x": float(self._cfg.scale_x),
            "scale_y": float(self._cfg.scale_y),
            "screen_x": float(sx),
            "screen_y": float(sy),
            "final_x": float(fx),
            "final_y": float(fy),
        }
        if within_selector:
            ev["within"] = str(within_selector)
        self._emit(ev)

    async def interact(self, *, selector: str, text: Optional[str]) -> None:
        assert self._browser is not None
        os_in = self._ensure_os()

        pt = await self.locate_point(selector)
        sx, sy = viewport_to_screen(
            pt.x,
            pt.y,
            scale_x=self._cfg.scale_x,
            scale_y=self._cfg.scale_y,
            offset_x=self._cfg.offset_x,
            offset_y=self._cfg.offset_y,
        )
        fx, fy = apply_noise(sx, sy, noise=self._cfg.noise, rng=self._noise_rng)
        self._emit_point(
            action="interact",
            selector=selector,
            within_selector=None,
            pt=pt,
            sx=sx,
            sy=sy,
            fx=fx,
            fy=fy,
        )

        await maybe_bring_to_front(self._browser)
        if self._cfg.pre_interact_delay_s > 0:
            await asyncio.sleep(self._cfg.pre_interact_delay_s)
        os_in.move_to(fx, fy, profile=self._cfg.mouse)
        os_in.click()

        if text:
            if self._cfg.post_click_delay_s > 0:
                await asyncio.sleep(self._cfg.post_click_delay_s)
            await os_in.human_type(text, profile=self._cfg.typing)
            if self._cfg.press_enter:
                os_in.press("enter")

    async def click(self, selector: str, *, within_selector: str | None = None) -> None:
        assert self._browser is not None
        if self._page is None:
            raise RuntimeError("click() called before navigate()")

        os_in = self._ensure_os()
        pt = await self.locate_point(selector, within_selector=within_selector)
        sx, sy = viewport_to_screen(
            pt.x,
            pt.y,
            scale_x=self._cfg.scale_x,
            scale_y=self._cfg.scale_y,
            offset_x=self._cfg.offset_x,
            offset_y=self._cfg.offset_y,
        )
        fx, fy = apply_noise(sx, sy, noise=self._cfg.noise, rng=self._noise_rng)
        self._emit_point(
            action="click",
            selector=selector,
            within_selector=within_selector,
            pt=pt,
            sx=sx,
            sy=sy,
            fx=fx,
            fy=fy,
        )

        await maybe_bring_to_front(self._browser)
        if self._cfg.pre_interact_delay_s > 0:
            await asyncio.sleep(self._cfg.pre_interact_delay_s)
        os_in.move_to(fx, fy, profile=self._cfg.mouse)
        os_in.click()

    async def type(
        self,
        selector: str,
        text: str,
        *,
        within_selector: str | None = None,
        click_first: bool = True,
        press_enter: bool = False,
        post_click_delay_s: float | None = None,
    ) -> None:
        assert self._browser is not None
        if self._page is None:
            raise RuntimeError("type() called before navigate()")

        os_in = self._ensure_os()
        if click_first:
            await self.click(selector, within_selector=within_selector)
        else:
            await maybe_bring_to_front(self._browser)
            if self._cfg.pre_interact_delay_s > 0:
                await asyncio.sleep(self._cfg.pre_interact_delay_s)

        delay = self._cfg.post_click_delay_s if post_click_delay_s is None else float(post_click_delay_s)
        if delay > 0:
            await asyncio.sleep(delay)
        await os_in.human_type(str(text), profile=self._cfg.typing)
        if press_enter:
            os_in.press("enter")

    async def press(self, key: str) -> None:
        assert self._browser is not None
        os_in = self._ensure_os()
        await maybe_bring_to_front(self._browser)
        if self._cfg.pre_interact_delay_s > 0:
            await asyncio.sleep(self._cfg.pre_interact_delay_s)
        os_in.press(key)

    async def wait_for_selector(
        self,
        selector: str,
        *,
        within_selector: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        if self._page is None:
            raise RuntimeError("wait_for_selector() called before navigate()")
        t = self._cfg.timeout_s if timeout_s is None else float(timeout_s)
        await wait_for_selector(self._page, selector, within_selector=within_selector, timeout_s=float(t))

    async def extract_text(
        self,
        selector: str,
        *,
        within_selector: str | None = None,
        timeout_s: float | None = None,
    ) -> str:
        if self._page is None:
            raise RuntimeError("extract_text() called before navigate()")

        t = self._cfg.timeout_s if timeout_s is None else float(timeout_s)
        if t > 0:
            await wait_for_selector(self._page, selector, within_selector=within_selector, timeout_s=float(t))
        return await selector_text_content(self._page, selector, within_selector=within_selector)

    async def wait_for_text(
        self,
        selector: str,
        *,
        contains: str,
        within_selector: str | None = None,
        timeout_s: float | None = None,
        poll_s: float | None = None,
    ) -> str:
        if self._page is None:
            raise RuntimeError("wait_for_text() called before navigate()")

        loop = asyncio.get_running_loop()
        t = self._cfg.timeout_s if timeout_s is None else float(timeout_s)
        deadline = loop.time() + float(t)
        poll = 0.05 if poll_s is None else float(poll_s)
        last_text: str | None = None
        last_exc: Exception | None = None

        while True:
            try:
                last_text = await selector_text_content(self._page, selector, within_selector=within_selector)
                if str(contains) in last_text:
                    if self._emit is not None:
                        ev: dict[str, Any] = {
                            "event": "wait_for_text.ok",
                            "selector": str(selector),
                            "contains": str(contains),
                            "chars": int(len(last_text)),
                        }
                        if within_selector:
                            ev["within"] = str(within_selector)
                        self._emit(ev)
                    return last_text
            except Exception as e:
                last_exc = e

            if loop.time() >= deadline:
                blob = ""
                if last_text:
                    snip = last_text
                    if len(snip) > 200:
                        snip = snip[:200] + "..."
                    blob = f" last_text={snip!r}"
                if within_selector:
                    raise TimeoutError(
                        f"Timed out waiting for text {contains!r} in selector: {selector} within {within_selector}.{blob}"
                    ) from last_exc
                raise TimeoutError(
                    f"Timed out waiting for text {contains!r} in selector: {selector}.{blob}"
                ) from last_exc

            await asyncio.sleep(poll)


def default_dry_run() -> bool:
    """
    Best-effort heuristic for default dry-run.

    - Linux: if neither X11 nor Wayland display env vars are set, assume no GUI.
    - macOS/Windows: do not key off DISPLAY (often unset even in GUI sessions).
    """
    override = _env_first(os.environ, "GWD_DRY_RUN", "GPT_WEB_DRIVER_DRY_RUN")
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "y", "on"}

    import sys

    if sys.platform.startswith("linux"):
        return (os.environ.get("DISPLAY") in (None, "")) and (os.environ.get("WAYLAND_DISPLAY") in (None, ""))
    return False


async def run_single(
    config: RunConfig,
    *,
    emit: Callable[[dict[str, Any]], None] | None = None,
    include_text_in_events: bool = False,
) -> None:
    async with FlowRunner(config, emit=emit, include_text_in_events=include_text_in_events) as runner:
        await runner.navigate(config.url)
        await runner.interact(selector=config.selector, text=config.text)


async def run_demo(
    config: RunConfig,
    *,
    repo_root: Path,
    emit: Callable[[dict[str, Any]], None] | None = None,
    include_text_in_events: bool = False,
) -> None:
    server = serve_directory(repo_root)
    try:
        url = f"{server.base_url}/sample-body.html"
        async with FlowRunner(config, emit=emit, include_text_in_events=include_text_in_events) as runner:
            await runner.navigate(url)
            await runner.interact(selector=config.selector, text=config.text)
            # Show multi-step behavior in a single session by re-running an action.
            await runner.interact(selector=config.selector, text=config.text)
    finally:
        server.close()
