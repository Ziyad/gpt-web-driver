from __future__ import annotations

from typing import Any, Optional


async def stealth_init(page: Any, *, uc_module: Optional[Any] = None) -> None:
    """
    Disable 'noisy' CDP domains immediately after connecting to the page.

    This intentionally avoids enabling Runtime, Log, and Debugger, and attempts
    to defuse breakpoint traps.
    """
    uc = uc_module
    if uc is None:
        import nodriver as uc  # type: ignore[assignment]

    async def _best_effort_send(msg: Any) -> None:
        try:
            await page.send(msg)
        except Exception:
            return

    # If domains are already disabled or the API differs, treat this as best-effort.
    await _best_effort_send(uc.cdp.runtime.disable())
    await _best_effort_send(uc.cdp.log.disable())
    await _best_effort_send(uc.cdp.debugger.disable())
    await _best_effort_send(uc.cdp.debugger.set_breakpoints_active(active=False))
