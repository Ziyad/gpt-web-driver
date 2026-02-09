from __future__ import annotations

import contextlib
import random
import sys
from dataclasses import dataclass
from typing import Optional

from ..os_input import OsInput
from ..core.physics import CognitiveTyper, CognitiveTyperConfig


def _paste_hotkey() -> tuple[str, str]:
    return ("command", "v") if sys.platform == "darwin" else ("ctrl", "v")


@dataclass(frozen=True)
class HybridInputConfig:
    paste_threshold_chars: int = 300
    typer: CognitiveTyperConfig = CognitiveTyperConfig()


class _ClipboardHygiene:
    def __init__(self) -> None:
        self._enabled = False
        self._saved: Optional[str] = None
        self._pyperclip = None

    def __enter__(self) -> "_ClipboardHygiene":
        try:
            import pyperclip  # type: ignore

            self._pyperclip = pyperclip
            self._saved = pyperclip.paste()
            self._enabled = True
        except Exception:
            self._enabled = False
        return self

    def copy(self, text: str) -> None:
        if not self._enabled or self._pyperclip is None:
            raise RuntimeError("pyperclip is unavailable; cannot use smart paste")
        self._pyperclip.copy(str(text))

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._enabled or self._pyperclip is None:
            return
        with contextlib.suppress(Exception):
            self._pyperclip.copy("" if self._saved is None else str(self._saved))


class HybridInput:
    """
    High-level text entry:
    - short text: cognitive typing
    - long text: smart paste with clipboard hygiene
    """

    def __init__(
        self,
        os_input: OsInput,
        *,
        cfg: HybridInputConfig | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._os = os_input
        self._cfg = cfg or HybridInputConfig()
        self._typer = CognitiveTyper(os_input, rng=rng, cfg=self._cfg.typer)

    async def smart_enter(self, text: str) -> None:
        s = str(text)
        if len(s) >= int(self._cfg.paste_threshold_chars):
            # Smart paste: preserve clipboard, load payload, paste, then restore.
            try:
                with _ClipboardHygiene() as cb:
                    cb.copy(s)
                    self._os.hotkey(*_paste_hotkey())
                return
            except Exception:
                # Fall back to typing if clipboard tooling is unavailable.
                pass

        await self._typer.type_text(s)
