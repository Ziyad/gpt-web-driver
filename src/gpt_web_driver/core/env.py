from __future__ import annotations

from typing import Mapping, Optional


def _env_first(env: Mapping[str, str], *keys: str) -> Optional[str]:
    """Return the value of the first key present in *env*, or ``None``."""
    for k in keys:
        v = env.get(k)
        if v is not None:
            return v
    return None
