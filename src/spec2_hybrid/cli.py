from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Optional

from .browser import default_browser_channel, default_browser_sandbox, default_download_browser
from .geometry import Noise
from .os_input import MouseProfile, TypingProfile
from .runner import RunConfig, default_dry_run, run_demo, run_single


def _path_or_none(s: Optional[str]) -> Optional[Path]:
    if s is None:
        return None
    return Path(s).expanduser()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gpt-web-driver")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--selector", default="#prompt-textarea")
        sp.add_argument("--text", default="Hello, this is a test prompt.")
        sp.add_argument("--no-enter", action="store_true", help="Do not press Enter after typing.")
        sp.add_argument("--timeout", type=float, default=20.0)

        sp.add_argument(
            "--browser-path",
            default=None,
            help="Path to a Chrome/Chromium executable (overrides auto-detection and auto-download).",
        )
        sp.add_argument(
            "--browser-channel",
            choices=["stable", "beta", "dev", "canary"],
            default=default_browser_channel(),
            help="Channel to download when auto-downloading Chrome for Testing.",
        )
        sp.add_argument(
            "--download-browser",
            action=argparse.BooleanOptionalAction,
            default=default_download_browser(),
            help="Allow automatic download of Chrome for Testing when no browser is found.",
        )
        sp.add_argument(
            "--sandbox",
            action=argparse.BooleanOptionalAction,
            default=default_browser_sandbox(),
            help="Enable the Chrome sandbox (disable with --no-sandbox if Chrome fails to launch in WSL/containers).",
        )
        sp.add_argument(
            "--browser-cache-dir",
            default=None,
            help="Override browser cache directory (defaults to XDG_CACHE_HOME/gpt-web-driver or ~/.cache/gpt-web-driver).",
        )
        sp.add_argument(
            "--cdp-host",
            default=None,
            help="Connect to an existing Chrome instance via CDP (host). Requires --cdp-port. "
            "When set, gpt-web-driver will not launch a local browser.",
        )
        sp.add_argument(
            "--cdp-port",
            default=None,
            type=int,
            help="Connect to an existing Chrome instance via CDP (port). Requires --cdp-host.",
        )

        sp.add_argument("--offset-x", type=float, default=0.0)
        sp.add_argument("--offset-y", type=float, default=80.0)

        sp.add_argument("--noise-x", type=int, default=12)
        sp.add_argument("--noise-y", type=int, default=5)

        sp.add_argument("--move-min", type=float, default=0.2)
        sp.add_argument("--move-max", type=float, default=0.6)

        sp.add_argument("--type-min", type=float, default=0.05)
        sp.add_argument("--type-max", type=float, default=0.15)

        sp.add_argument(
            "--dry-run",
            action=argparse.BooleanOptionalAction,
            default=default_dry_run(),
            help="Do not execute OS-level input; log intended actions instead.",
        )

        sp.add_argument("--real-profile", default=None)
        sp.add_argument("--shim-profile", default=None)

    run = sub.add_parser("run", help="Navigate to a URL and interact with one selector.")
    run.add_argument("--url", required=True)
    add_common(run)

    demo = sub.add_parser("demo", help="Serve sample-body.html locally and run the hybrid flow.")
    add_common(demo)

    return p


def _make_config(ns: argparse.Namespace) -> RunConfig:
    cdp_host = getattr(ns, "cdp_host", None)
    cdp_port = getattr(ns, "cdp_port", None)
    if (cdp_host is None) ^ (cdp_port is None):
        raise SystemExit("--cdp-host and --cdp-port must be provided together")

    return RunConfig(
        url=getattr(ns, "url", ""),
        selector=ns.selector,
        text=(ns.text or None),
        press_enter=not ns.no_enter,
        dry_run=bool(ns.dry_run),
        timeout_s=float(ns.timeout),
        browser_path=_path_or_none(ns.browser_path),
        browser_channel=str(ns.browser_channel),
        download_browser=bool(ns.download_browser),
        sandbox=bool(ns.sandbox),
        browser_cache_dir=_path_or_none(ns.browser_cache_dir),
        cdp_host=(str(cdp_host) if cdp_host else None),
        cdp_port=(int(cdp_port) if cdp_port is not None else None),
        offset_x=float(ns.offset_x),
        offset_y=float(ns.offset_y),
        noise=Noise(x_px=int(ns.noise_x), y_px=int(ns.noise_y)),
        mouse=MouseProfile(min_move_duration_s=float(ns.move_min), max_move_duration_s=float(ns.move_max)),
        typing=TypingProfile(min_delay_s=float(ns.type_min), max_delay_s=float(ns.type_max)),
        real_profile=_path_or_none(ns.real_profile),
        shim_profile=_path_or_none(ns.shim_profile),
    )


def main(argv: Optional[list[str]] = None) -> int:
    ns = build_parser().parse_args(argv)
    cfg = _make_config(ns)

    if ns.cmd == "run":
        asyncio.run(run_single(cfg))
        return 0

    if ns.cmd == "demo":
        repo_root = Path(__file__).resolve().parents[2]
        asyncio.run(run_demo(cfg, repo_root=repo_root))
        return 0

    raise SystemExit(f"unknown command: {ns.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
