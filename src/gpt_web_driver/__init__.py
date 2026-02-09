from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from .runner import FlowRunner, RunConfig, default_dry_run, run_demo, run_single
from .stealth import stealth_init

try:
    __version__ = _pkg_version("gpt-web-driver")
except PackageNotFoundError:  # pragma: no cover - only hit in editable/dev without metadata
    __version__ = "0.0.0"

# Friendlier public name. Keep FlowRunner as the implementation name.
Driver = FlowRunner

__all__ = [
    "__version__",
    "Driver",
    "FlowRunner",
    "RunConfig",
    "default_dry_run",
    "run_demo",
    "run_single",
    "stealth_init",
]

