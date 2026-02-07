from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class ProfileConfig:
    real_profile_dir: Path
    shim_profile_dir: Path
    exclude_globs: Sequence[str] = ("Cache*", "Code Cache", "GPUCache", "Service Worker", "ShaderCache")


def _ignore_patterns_for_copy(exclude_globs: Sequence[str]):
    return shutil.ignore_patterns(*exclude_globs)


def ensure_profile(config: ProfileConfig) -> None:
    """
    Clone a Chrome profile dir into a shim profile dir, excluding cache-like paths.

    This is opt-in: callers should pass explicit paths.
    """
    if config.shim_profile_dir.exists():
        return

    if not config.real_profile_dir.exists():
        raise FileNotFoundError(f"real profile dir does not exist: {config.real_profile_dir}")

    config.shim_profile_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        config.real_profile_dir,
        config.shim_profile_dir,
        ignore=_ignore_patterns_for_copy(config.exclude_globs),
        dirs_exist_ok=False,
    )

