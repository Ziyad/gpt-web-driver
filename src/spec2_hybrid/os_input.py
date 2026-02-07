from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Optional


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
    ) -> None:
        self._dry_run = dry_run
        self._rng = rng or random
        self._pag = pyautogui_module
        if not self._dry_run and self._pag is None:
            import pyautogui as pag  # type: ignore

            self._pag = pag

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def move_to(self, x: float, y: float, *, profile: MouseProfile) -> None:
        duration = self._rng.uniform(profile.min_move_duration_s, profile.max_move_duration_s)
        if self._dry_run:
            print(f"[dry-run] moveTo x={x:.2f} y={y:.2f} duration={duration:.3f}")
            return
        assert self._pag is not None
        self._pag.moveTo(x, y, duration=duration)

    def click(self) -> None:
        if self._dry_run:
            print("[dry-run] click")
            return
        assert self._pag is not None
        self._pag.click()

    def write_char(self, char: str) -> None:
        if self._dry_run:
            print(f"[dry-run] write {char!r}")
            return
        assert self._pag is not None
        self._pag.write(char)

    def press(self, key: str) -> None:
        if self._dry_run:
            print(f"[dry-run] press {key!r}")
            return
        assert self._pag is not None
        self._pag.press(key)

    async def human_type(self, text: str, *, profile: TypingProfile) -> None:
        for ch in text:
            self.write_char(ch)
            await asyncio.sleep(self._rng.uniform(profile.min_delay_s, profile.max_delay_s))

