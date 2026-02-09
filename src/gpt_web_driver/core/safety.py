from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, Optional


def beep() -> None:
    """
    Best-effort audible/visible alert.
    """
    try:
        if sys.platform.startswith("win"):
            import winsound  # type: ignore

            winsound.MessageBeep()
            return
    except Exception:
        pass

    # Terminal bell.
    try:
        sys.stderr.write("\a")
        sys.stderr.flush()
    except Exception:
        return


@dataclass(frozen=True)
class DeadManSwitch:
    """
    Keyword-based interruption detection.
    """

    keywords: tuple[str, ...] = ("challenge", "verify", "captcha", "are you human", "unusual traffic")

    def triggered_by(self, text: str) -> Optional[str]:
        blob = str(text or "").lower()
        for k in self.keywords:
            ks = str(k).lower()
            if ks and ks in blob:
                return ks
        return None


def maybe_move_active_window_to_virtual_desktop(desktop_index: int) -> None:
    """
    Best-effort "hide" strategy: move the currently active window to a different virtual desktop.

    This is intentionally best-effort and no-ops when platform tooling isn't available.
    """
    idx = int(desktop_index)
    if idx < 0:
        return

    if sys.platform.startswith("linux"):
        # `wmctrl` is the least-bad cross-DE option; requires X11/XWayland.
        try:
            subprocess.run(
                ["wmctrl", "-r", ":ACTIVE:", "-t", str(idx)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return

    if sys.platform.startswith("win"):
        # Windows: try pyvda (optional dependency). This API differs across versions,
        # so treat this as best-effort and never crash the automation.
        try:
            from pyvda import AppView, VirtualDesktop  # type: ignore

            view = AppView.current()
            desk = VirtualDesktop(idx)
            view.move(desk)
        except Exception:
            return

