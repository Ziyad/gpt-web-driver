from __future__ import annotations

from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from ..stealth import stealth_init


def origin_from_url(url: str) -> Optional[str]:
    """
    Extract a CDP "origin" (scheme://host[:port]) from a URL.
    """
    try:
        p = urlparse(str(url))
    except Exception:
        return None
    if not p.scheme or not p.netloc:
        return None
    return f"{p.scheme}://{p.netloc}"


async def grant_permissions(
    page: Any,
    *,
    origin: str,
    permissions: Iterable[str] = ("clipboardReadWrite", "notifications"),
    uc_module: Optional[Any] = None,
) -> None:
    """
    Best-effort pre-approval of permissions to avoid native popups interrupting OS input.

    This is intentionally resilient to nodriver/CDP API shape differences.
    """
    if not hasattr(page, "send"):
        return

    uc = uc_module
    if uc is None:
        try:
            import nodriver as uc  # type: ignore[assignment]
        except Exception:
            uc = None

    perms = [str(p) for p in permissions]
    origin_s = str(origin)

    # Prefer nodriver generated CDP messages (real nodriver Tabs typically don't accept dict CDP).
    if uc is not None:
        try:
            browser = getattr(getattr(uc, "cdp", None), "browser", None)
            fn = getattr(browser, "grant_permissions", None) if browser is not None else None
            if callable(fn):
                msg = None
                try:
                    msg = fn(perms, origin_s)
                except TypeError:
                    try:
                        msg = fn(permissions=perms, origin=origin_s)
                    except TypeError:
                        msg = None
                if msg is not None:
                    try:
                        await page.send(msg)
                        return
                    except Exception:
                        pass
        except Exception:
            pass

    # Generic dict CDP fallback (useful for unit tests / alternative shims).
    try:
        await page.send(
            {"method": "Browser.grantPermissions", "params": {"origin": origin_s, "permissions": perms}}
        )
    except Exception:
        return


async def optimize_connection(
    page: Any,
    *,
    url_for_permissions: str | None = None,
    uc_module: Optional[Any] = None,
) -> None:
    """
    "Silence protocol" + best-effort permission pre-approval.
    """
    await stealth_init(page, uc_module=uc_module)
    if url_for_permissions:
        origin = origin_from_url(url_for_permissions)
        if origin:
            await grant_permissions(page, origin=origin, uc_module=uc_module)

