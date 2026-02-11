from __future__ import annotations

import asyncio
import random
import shutil
from dataclasses import dataclass, replace as _dc_replace
from pathlib import Path
from typing import Any, Callable, Optional

from platformdirs import user_cache_dir

from .actions.input import HybridInput, HybridInputConfig
from .core.driver import optimize_connection
from .core.observer import last_assistant_message_text, wait_for_assistant_reply
from .core.physics import NeuromotorMouse, NeuromotorMouseConfig
from .core.safety import DeadManSwitch, beep, maybe_move_active_window_to_virtual_desktop
from .geometry import apply_noise, viewport_to_screen
from .nodriver_dom import (
    dom_get_outer_html,
    dom_query_selector_node_id,
    html_to_text,
    maybe_bring_to_front,
    selector_viewport_gaussian_point,
    wait_for_selector,
)
from .profile import ProfileConfig, ensure_profile
from .runner import FlowRunner, RunConfig


def default_shadow_profile_dir() -> Path:
    """
    Default shadow profile directory (persistent across runs).
    """
    # Spec suggests "~/.nibs-profile"; use the cache dir to avoid cluttering $HOME.
    return Path(user_cache_dir("gpt-web-driver")) / "nibs-profile"


@dataclass(frozen=True)
class ChatUIConfig:
    url: str
    input_selector: str = "#prompt-textarea"
    message_selector: str = "[data-message-author-role]"
    content_selector: str = ".whitespace-pre-wrap, .markdown"
    timeout_s: float = 90.0
    stable_s: float = 1.2
    poll_s: float = 0.25
    # Best-effort: move active browser window to this virtual desktop index on startup.
    virtual_desktop: int | None = None
    deadman: DeadManSwitch = DeadManSwitch()


@dataclass(frozen=True)
class NibsConfig:
    run: RunConfig
    ui: ChatUIConfig
    # Hybrid input gate.
    paste_threshold_chars: int = 300
    # Neuromotor mouse.
    mouse: NeuromotorMouseConfig = NeuromotorMouseConfig()


class NibsSession:
    """
    A long-lived headed browser session intended for the OpenAI-compatible API server.
    """

    def __init__(
        self,
        cfg: NibsConfig,
        *,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._emit = emit
        self._runner: FlowRunner | None = None
        seed = cfg.run.seed
        if seed is None:
            # Default: non-deterministic "natural" variability.
            self._mouse_rng = random.Random()
            self._typing_rng = random.Random()
        else:
            # Deterministic when explicitly seeded.
            self._mouse_rng = random.Random(int(seed))
            self._typing_rng = random.Random(int(seed) ^ 0x1234ABCD)
        self._lock = asyncio.Lock()
        self._paused_reason: str | None = None

    @property
    def paused_reason(self) -> str | None:
        return self._paused_reason

    def resume(self) -> None:
        self._paused_reason = None

    async def start(self) -> None:
        if self._runner is not None:
            return

        run_cfg = self._cfg.run

        # Ensure we always have a profile dir for session continuity.
        # If a real profile is provided and the shim path is *not* user-specified,
        # refresh the shadow copy on startup (matches the "shadow profile" strategy).
        shim_is_default = run_cfg.shim_profile is None
        shim = run_cfg.shim_profile or default_shadow_profile_dir()
        real = run_cfg.real_profile
        if real is not None:
            if shim_is_default and shim.exists():
                shutil.rmtree(shim, ignore_errors=True)
            ensure_profile(ProfileConfig(real_profile_dir=real, shim_profile_dir=shim))
        else:
            shim.mkdir(parents=True, exist_ok=True)

        # Inject shim_profile into the runner config (frozen dataclass).
        run_cfg = _dc_replace(run_cfg, shim_profile=shim)

        r = FlowRunner(run_cfg, emit=self._emit)
        await r.start()
        self._runner = r

        # Navigate once; keep session/tab alive.
        await r.navigate(self._cfg.ui.url)
        if r.page is not None:
            await optimize_connection(r.page, url_for_permissions=str(self._cfg.ui.url))

        if self._cfg.ui.virtual_desktop is not None:
            await maybe_bring_to_front(r.browser)
            maybe_move_active_window_to_virtual_desktop(int(self._cfg.ui.virtual_desktop))

    async def close(self) -> None:
        if self._runner is None:
            return
        await self._runner.close()
        self._runner = None

    async def _deadman_check(self) -> None:
        if self._paused_reason is not None:
            raise RuntimeError(f"paused: {self._paused_reason}")

    async def _page_snapshot_text(self) -> str:
        """
        Best-effort offline snapshot of the current page text for dead-man checks.
        """
        if self._runner is None or self._runner.page is None:
            return ""
        page = self._runner.page
        try:
            nid = await dom_query_selector_node_id(page, "body")
            if not nid:
                return ""
            html = await dom_get_outer_html(page, int(nid))
            return html_to_text(html)
        except Exception:
            return ""

    async def chat_completion(self, prompt: str) -> str:
        """
        Send a prompt and return the assistant reply text.
        """
        async with self._lock:
            await self._deadman_check()
            if self._runner is None:
                raise RuntimeError("session not started")
            r = self._runner
            if r.page is None:
                raise RuntimeError("no page (navigate not called)")

            # Capture a baseline so we don't immediately return an old assistant message.
            baseline: str | None = None
            try:
                baseline = await last_assistant_message_text(
                    r.page,
                    message_selector=self._cfg.ui.message_selector,
                    content_selector=self._cfg.ui.content_selector,
                    timeout_s=0.0,
                )
            except Exception:
                baseline = None

            # Wait for input selector to exist (DOM polling).
            await wait_for_selector(r.page, self._cfg.ui.input_selector, timeout_s=float(self._cfg.ui.timeout_s))

            # Gaussian targeting inside the element box.
            pt = await selector_viewport_gaussian_point(
                r.page,
                self._cfg.ui.input_selector,
                rng=self._mouse_rng,
            )

            run_cfg = r.config
            sx, sy = viewport_to_screen(
                pt.x,
                pt.y,
                scale_x=run_cfg.scale_x,
                scale_y=run_cfg.scale_y,
                offset_x=run_cfg.offset_x,
                offset_y=run_cfg.offset_y,
            )
            fx, fy = apply_noise(sx, sy, noise=run_cfg.noise, rng=self._mouse_rng)

            # OS input path.
            await maybe_bring_to_front(r.browser)
            if run_cfg.pre_interact_delay_s > 0:
                await asyncio.sleep(run_cfg.pre_interact_delay_s)

            os_in = r.os_input()
            mouse = NeuromotorMouse(os_in, rng=self._mouse_rng, cfg=self._cfg.mouse)
            # Incidental hover: take a slightly "imperfect" path that can cross other UI elements.
            try:
                if self._mouse_rng.random() < 0.30:
                    mx, my = os_in.position()
                    dx = float(fx - mx)
                    dy = float(fy - my)
                    # Perpendicular offset for a gentle curve.
                    px, py = -dy, dx
                    plen = (px * px + py * py) ** 0.5 or 1.0
                    px /= plen
                    py /= plen

                    t = float(self._mouse_rng.uniform(0.25, 0.65))
                    bend = float(self._mouse_rng.uniform(-60.0, 60.0))
                    ix = float(mx + dx * t + px * bend)
                    iy = float(my + dy * t + py * bend)

                    await mouse.move_to(ix, iy, duration_s=float(self._mouse_rng.uniform(0.18, 0.35)))
                    await asyncio.sleep(float(self._mouse_rng.uniform(0.03, 0.12)))
            except Exception:
                pass
            await mouse.move_to(fx, fy)
            os_in.click()
            if run_cfg.post_click_delay_s > 0:
                await asyncio.sleep(run_cfg.post_click_delay_s)

            hybrid = HybridInput(
                os_in,
                cfg=HybridInputConfig(paste_threshold_chars=int(self._cfg.paste_threshold_chars)),
                rng=self._typing_rng,
            )
            await hybrid.smart_enter(str(prompt))
            # Always press Enter for a chat completion.
            os_in.press("enter")

            # While waiting for the response, inertial "flick" scrolling keeps the stream visible.
            loop = asyncio.get_running_loop()
            next_flick_at = loop.time() + self._mouse_rng.uniform(0.2, 0.6)
            flick_task: asyncio.Task[None] | None = None

            async def _flick() -> None:
                mag = -520
                delay_s = 0.02
                for _ in range(7):
                    try:
                        os_in.scroll(int(mag))
                    except Exception:
                        return
                    await asyncio.sleep(delay_s)
                    mag = int(mag * 0.55)
                    delay_s = float(delay_s * 1.35)

            def _on_poll() -> None:
                nonlocal next_flick_at, flick_task
                now = loop.time()
                if now < next_flick_at:
                    return
                if flick_task is not None and not flick_task.done():
                    return
                flick_task = asyncio.create_task(_flick())
                next_flick_at = now + self._mouse_rng.uniform(1.2, 2.4)

            try:
                reply = await wait_for_assistant_reply(
                    r.page,
                    message_selector=self._cfg.ui.message_selector,
                    content_selector=self._cfg.ui.content_selector,
                    baseline_text=baseline,
                    timeout_s=float(self._cfg.ui.timeout_s),
                    stable_s=float(self._cfg.ui.stable_s),
                    poll_s=float(self._cfg.ui.poll_s),
                    on_poll=_on_poll,
                    interruption_keywords=self._cfg.ui.deadman.keywords,
                )
            except Exception as e:
                # Dead man's switch triggers: pause and require operator intervention.
                k = self._cfg.ui.deadman.triggered_by(str(e)) or self._cfg.ui.deadman.triggered_by(
                    await self._page_snapshot_text()
                )
                if k is not None or "challenge" in str(e).lower() or "verify" in str(e).lower():
                    self._paused_reason = str(e)
                    beep()
                raise
            finally:
                if flick_task is not None and not flick_task.done():
                    flick_task.cancel()
                    try:
                        await flick_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass
            return reply
