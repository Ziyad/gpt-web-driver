from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from .flow import FlowResult, FlowSpecError, load_flow, run_flow
from .nibs import ChatUIConfig, NibsConfig, NibsSession, default_shadow_profile_dir
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
    "ChatUIConfig",
    "FlowRunner",
    "FlowResult",
    "FlowSpecError",
    "NibsConfig",
    "NibsSession",
    "RunConfig",
    "default_dry_run",
    "default_shadow_profile_dir",
    "load_flow",
    "run_demo",
    "run_flow",
    "run_single",
    "stealth_init",
]

