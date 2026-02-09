from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class TypingProfile:
    min_delay_s: float = 0.05
    max_delay_s: float = 0.15


@dataclass(frozen=True)
class MouseProfile:
    min_move_duration_s: float = 0.2
    max_move_duration_s: float = 0.6


class OsInput:
    """
    OS-level input wrapper.

    - In `dry_run` mode, this does not import or call pyautogui.
    - In non-dry-run mode, pyautogui is imported lazily to avoid GUI import
      failures for unit tests and CI.
    """

    def __init__(
        self,
        *,
        dry_run: bool,
        pyautogui_module: Optional[Any] = None,
        rng: random.Random | None = None,
        emit: Callable[[dict[str, Any]], None] | None = None,
        include_text_in_events: bool = False,
    ) -> None:
        self._dry_run = dry_run
        self._rng = rng or random
        self._emit = emit
        self._include_text_in_events = bool(include_text_in_events)
        self._pag = pyautogui_module
        if not self._dry_run and self._pag is None:
            try:
                import pyautogui as pag  # type: ignore

                self._pag = pag
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    "pyautogui is required for OS-level input. Install with: pip install 'gpt-web-driver[gui]' "
                    "(or run with --dry-run)."
                ) from e

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def move_to(self, x: float, y: float, *, profile: MouseProfile) -> None:
        duration = self._rng.uniform(profile.min_move_duration_s, profile.max_move_duration_s)
        ev = {
            "event": "os.move_to",
            "x": float(x),
            "y": float(y),
            "duration_s": float(duration),
            "dry_run": bool(self._dry_run),
        }

        if self._dry_run:
            if self._emit is not None:
                self._emit(ev)
            else:
                print(f"[dry-run] moveTo x={x:.2f} y={y:.2f} duration={duration:.3f}")
            return

        assert self._pag is not None
        self._pag.moveTo(x, y, duration=duration)
        if self._emit is not None:
            self._emit(ev)

    def click(self) -> None:
        ev = {"event": "os.click", "dry_run": bool(self._dry_run)}

        if self._dry_run:
            if self._emit is not None:
                self._emit(ev)
            else:
                print("[dry-run] click")
            return

        assert self._pag is not None
        self._pag.click()
        if self._emit is not None:
            self._emit(ev)

    def write_char(self, char: str) -> None:
        ev: dict[str, Any] = {"event": "os.write_char", "dry_run": bool(self._dry_run)}
        if self._include_text_in_events:
            ev["char"] = str(char)

        if self._dry_run:
            if self._emit is not None:
                if self._include_text_in_events:
                    self._emit(ev)
            else:
                print(f"[dry-run] write {char!r}")
            return

        assert self._pag is not None
        self._pag.write(char)
        if self._emit is not None:
            if self._include_text_in_events:
                self._emit(ev)

    def press(self, key: str) -> None:
        ev = {"event": "os.press", "key": str(key), "dry_run": bool(self._dry_run)}

        if self._dry_run:
            if self._emit is not None:
                self._emit(ev)
            else:
                print(f"[dry-run] press {key!r}")
            return

        assert self._pag is not None
        self._pag.press(key)
        if self._emit is not None:
            self._emit(ev)

    async def human_type(self, text: str, *, profile: TypingProfile) -> None:
        if self._emit is not None:
            ev: dict[str, Any] = {
                "event": "os.human_type",
                "chars": int(len(text)),
                "min_delay_s": float(profile.min_delay_s),
                "max_delay_s": float(profile.max_delay_s),
                "dry_run": bool(self._dry_run),
            }
            if self._include_text_in_events:
                ev["text"] = str(text)
            self._emit(ev)

        for ch in text:
            self.write_char(ch)
            await asyncio.sleep(self._rng.uniform(profile.min_delay_s, profile.max_delay_s))

