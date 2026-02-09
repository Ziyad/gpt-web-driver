from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import sys
import time
from pathlib import Path
from typing import Optional

from . import __version__
from .calibration import default_calibration_path, load_calibration, run_calibrate
from .browser import (
    BrowserNotFoundError,
    default_browser_cache_dir,
    default_browser_channel,
    default_browser_sandbox,
    default_download_browser,
    is_wsl,
    resolve_browser_executable_path,
)
from .flow import load_flow, run_flow
from .geometry import Noise
from .os_input import MouseProfile, TypingProfile
from .runner import RunConfig, default_dry_run, run_demo, run_single


def _path_or_none(s: Optional[str]) -> Optional[Path]:
    if s is None:
        return None
    return Path(s).expanduser()


def _parse_vars(pairs: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in pairs or []:
        s = str(raw)
        if "=" not in s:
            raise SystemExit(f"--var must be KEY=VALUE (got: {raw!r})")
        k, v = s.split("=", 1)
        k = k.strip()
        if not k:
            raise SystemExit(f"--var must be KEY=VALUE (got: {raw!r})")
        out[k] = v
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gpt-web-driver")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
            help="Override browser cache directory (defaults to the OS user cache dir, honoring XDG_CACHE_HOME on Linux).",
        )
        sp.add_argument(
            "--calibration",
            default=None,
            help="Path to a calibration JSON file produced by `gpt-web-driver calibrate` (applies scale + offsets).",
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

        sp.add_argument("--scale-x", type=float, default=None, help="Viewport->screen X scale (default: 1.0).")
        sp.add_argument("--scale-y", type=float, default=None, help="Viewport->screen Y scale (default: 1.0).")
        sp.add_argument("--offset-x", type=float, default=None, help="Viewport->screen X offset (default: 0).")
        sp.add_argument("--offset-y", type=float, default=None, help="Viewport->screen Y offset (default: 80).")

        sp.add_argument("--noise-x", type=int, default=12)
        sp.add_argument("--noise-y", type=int, default=5)

        sp.add_argument("--move-min", type=float, default=0.2)
        sp.add_argument("--move-max", type=float, default=0.6)

        sp.add_argument("--type-min", type=float, default=0.05)
        sp.add_argument("--type-max", type=float, default=0.15)

        sp.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Deterministic seed for noise + OS timing (useful for reproducible runs).",
        )
        sp.add_argument(
            "--pre-interact-delay",
            type=float,
            default=0.0,
            help="Sleep this many seconds right before OS-level interaction (gives you time to focus the browser).",
        )
        sp.add_argument(
            "--post-click-delay",
            type=float,
            default=0.5,
            help="Sleep this many seconds after click and before typing.",
        )

        sp.add_argument(
            "--dry-run",
            action=argparse.BooleanOptionalAction,
            default=default_dry_run(),
            help="Do not execute OS-level input; log intended actions instead.",
        )

        sp.add_argument(
            "--output",
            choices=["text", "jsonl"],
            default="text",
            help="Output format. Use jsonl for machine-readable event stream on stdout.",
        )
        sp.add_argument(
            "--include-text-in-output",
            action="store_true",
            help="Include typed text in jsonl output (may leak secrets).",
        )
        sp.add_argument(
            "--log-level",
            choices=["debug", "info", "warning", "error"],
            default="info",
            help="Logging verbosity (logs go to stderr).",
        )

        sp.add_argument("--real-profile", default=None)
        sp.add_argument("--shim-profile", default=None)

    run = sub.add_parser("run", help="Navigate to a URL and interact with one selector.")
    run.add_argument("--url", required=True)
    add_common(run)

    demo = sub.add_parser("demo", help="Serve sample-body.html locally and run the hybrid flow.")
    add_common(demo)

    flow = sub.add_parser("flow", help="Run a multi-step JSON flow file.")
    flow.add_argument("--flow", required=True, help="Path to a JSON flow file.")
    flow.add_argument(
        "--var",
        action="append",
        default=[],
        help="Set/override a flow variable (repeatable): --var KEY=VALUE",
    )
    add_common(flow)

    doctor = sub.add_parser("doctor", help="Print environment diagnostics (no browser automation).")
    doctor.add_argument(
        "--browser-path",
        default=None,
        help="Path to a Chrome/Chromium executable (overrides auto-detection).",
    )
    doctor.add_argument(
        "--browser-channel",
        choices=["stable", "beta", "dev", "canary"],
        default=default_browser_channel(),
        help="Channel to download when auto-downloading Chrome for Testing.",
    )
    doctor.add_argument(
        "--download-browser",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Allow doctor to auto-download Chrome for Testing if no browser is found (off by default).",
    )
    doctor.add_argument(
        "--sandbox",
        action=argparse.BooleanOptionalAction,
        default=default_browser_sandbox(),
        help="Enable the Chrome sandbox (disable with --no-sandbox if Chrome fails to launch in WSL/containers).",
    )
    doctor.add_argument(
        "--browser-cache-dir",
        default=None,
        help="Override browser cache directory (defaults to the OS user cache dir, honoring XDG_CACHE_HOME on Linux).",
    )
    doctor.add_argument(
        "--cdp-host",
        default=None,
        help="Connect to an existing Chrome instance via CDP (host). Requires --cdp-port.",
    )
    doctor.add_argument(
        "--cdp-port",
        default=None,
        type=int,
        help="Connect to an existing Chrome instance via CDP (port). Requires --cdp-host.",
    )
    doctor.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=default_dry_run(),
        help="Show/override the dry-run default that run/demo will use in this environment.",
    )
    doctor.add_argument(
        "--output",
        choices=["text", "jsonl"],
        default="text",
        help="Output format. Use jsonl for machine-readable event stream on stdout.",
    )
    doctor.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default="info",
        help="Logging verbosity (logs go to stderr).",
    )

    calibrate = sub.add_parser("calibrate", help="Interactively calibrate viewport->screen mapping (scale + offset).")
    calibrate.add_argument("--timeout", type=float, default=20.0)
    calibrate.add_argument(
        "--browser-path",
        default=None,
        help="Path to a Chrome/Chromium executable (overrides auto-detection and auto-download).",
    )
    calibrate.add_argument(
        "--browser-channel",
        choices=["stable", "beta", "dev", "canary"],
        default=default_browser_channel(),
        help="Channel to download when auto-downloading Chrome for Testing.",
    )
    calibrate.add_argument(
        "--download-browser",
        action=argparse.BooleanOptionalAction,
        default=default_download_browser(),
        help="Allow automatic download of Chrome for Testing when no browser is found.",
    )
    calibrate.add_argument(
        "--sandbox",
        action=argparse.BooleanOptionalAction,
        default=default_browser_sandbox(),
        help="Enable the Chrome sandbox (disable with --no-sandbox if Chrome fails to launch in WSL/containers).",
    )
    calibrate.add_argument(
        "--browser-cache-dir",
        default=None,
        help="Override browser cache directory (defaults to platformdirs/user cache dir).",
    )
    calibrate.add_argument(
        "--cdp-host",
        default=None,
        help="Connect to an existing Chrome instance via CDP (host). Requires --cdp-port.",
    )
    calibrate.add_argument(
        "--cdp-port",
        default=None,
        type=int,
        help="Connect to an existing Chrome instance via CDP (port). Requires --cdp-host.",
    )
    calibrate.add_argument("--real-profile", default=None)
    calibrate.add_argument("--shim-profile", default=None)
    calibrate.add_argument(
        "--write-calibration",
        nargs="?",
        const=str(default_calibration_path()),
        default=None,
        help=f"Write calibration JSON (default: {default_calibration_path()}).",
    )
    calibrate.add_argument(
        "--output",
        choices=["text", "jsonl"],
        default="text",
        help="Output format. Use jsonl for machine-readable event stream on stdout.",
    )
    calibrate.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default="info",
        help="Logging verbosity (logs go to stderr).",
    )

    return p


def _make_config(ns: argparse.Namespace) -> RunConfig:
    cdp_host = getattr(ns, "cdp_host", None)
    cdp_port = getattr(ns, "cdp_port", None)
    if (cdp_host is None) ^ (cdp_port is None):
        raise SystemExit("--cdp-host and --cdp-port must be provided together")

    base_scale_x = 1.0
    base_scale_y = 1.0
    base_offset_x = 0.0
    base_offset_y = 80.0
    cal_path = _path_or_none(getattr(ns, "calibration", None))
    if cal_path is not None:
        try:
            cal = load_calibration(cal_path)
        except Exception as e:
            raise SystemExit(f"Failed to load calibration file {str(cal_path)!r}: {e}") from e
        base_scale_x = float(cal.scale_x)
        base_scale_y = float(cal.scale_y)
        base_offset_x = float(cal.offset_x)
        base_offset_y = float(cal.offset_y)

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
        scale_x=float(base_scale_x if getattr(ns, "scale_x", None) is None else ns.scale_x),
        scale_y=float(base_scale_y if getattr(ns, "scale_y", None) is None else ns.scale_y),
        offset_x=float(base_offset_x if getattr(ns, "offset_x", None) is None else ns.offset_x),
        offset_y=float(base_offset_y if getattr(ns, "offset_y", None) is None else ns.offset_y),
        noise=Noise(x_px=int(ns.noise_x), y_px=int(ns.noise_y)),
        mouse=MouseProfile(min_move_duration_s=float(ns.move_min), max_move_duration_s=float(ns.move_max)),
        typing=TypingProfile(min_delay_s=float(ns.type_min), max_delay_s=float(ns.type_max)),
        real_profile=_path_or_none(ns.real_profile),
        shim_profile=_path_or_none(ns.shim_profile),
        seed=(int(ns.seed) if ns.seed is not None else None),
        pre_interact_delay_s=float(ns.pre_interact_delay),
        post_click_delay_s=float(ns.post_click_delay),
    )


def _doctor(ns: argparse.Namespace, *, emit=None) -> None:
    cdp_host = getattr(ns, "cdp_host", None)
    cdp_port = getattr(ns, "cdp_port", None)
    if (cdp_host is None) ^ (cdp_port is None):
        raise SystemExit("--cdp-host and --cdp-port must be provided together")

    env = dict(os.environ)
    browser_cache_dir = _path_or_none(getattr(ns, "browser_cache_dir", None)) or default_browser_cache_dir(env)

    resolved_browser: str | None = None
    browser_error: str | None = None
    try:
        p = resolve_browser_executable_path(
            explicit_path=_path_or_none(getattr(ns, "browser_path", None)),
            download=bool(getattr(ns, "download_browser", False)),
            channel=str(getattr(ns, "browser_channel", default_browser_channel(env))),
            cache_dir=browser_cache_dir,
            env=env,
        )
        resolved_browser = str(p)
    except (BrowserNotFoundError, FileNotFoundError, ValueError) as e:
        browser_error = str(e)

    payload = {
        "event": "doctor",
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "machine": platform.machine(),
        "is_wsl": bool(is_wsl(env)),
        "display": {
            "DISPLAY": env.get("DISPLAY"),
            "WAYLAND_DISPLAY": env.get("WAYLAND_DISPLAY"),
        },
        "effective_dry_run": bool(getattr(ns, "dry_run", default_dry_run())),
        "default_download_browser": bool(default_download_browser(env)),
        "default_browser_channel": str(default_browser_channel(env)),
        "default_browser_sandbox": bool(default_browser_sandbox(env)),
        "browser_cache_dir": str(browser_cache_dir),
        "browser_resolved": resolved_browser,
        "browser_error": browser_error,
        "cdp": (
            {"host": str(cdp_host), "port": int(cdp_port)} if (cdp_host and (cdp_port is not None)) else None
        ),
    }

    if emit is not None:
        emit(payload)
        return

    lines = [
        "gpt-web-driver doctor",
        f"python:   {payload['python']}",
        f"platform: {payload['platform']} ({payload['machine']})",
        f"wsl:      {str(payload['is_wsl']).lower()}",
        f"display:  DISPLAY={payload['display']['DISPLAY']!r} WAYLAND_DISPLAY={payload['display']['WAYLAND_DISPLAY']!r}",
        f"dry-run:  {str(payload['effective_dry_run']).lower()}",
        f"sandbox:  {str(payload['default_browser_sandbox']).lower()} (default; override with --sandbox/--no-sandbox)",
        f"download: {str(payload['default_download_browser']).lower()} (default for run/demo; doctor uses --download-browser)",
        f"cache:    {payload['browser_cache_dir']}",
    ]
    if payload["cdp"] is not None:
        lines.append(f"cdp:      {payload['cdp']['host']}:{payload['cdp']['port']}")

    if payload["browser_resolved"]:
        lines.append(f"browser:  {payload['browser_resolved']}")
    else:
        lines.append("browser:  (not found)")
        if payload["browser_error"]:
            lines.append(f"error:    {payload['browser_error']}")

    sys.stdout.write("\n".join(lines) + "\n")


def main(argv: Optional[list[str]] = None) -> int:
    ns = build_parser().parse_args(argv)

    log_level = getattr(logging, str(ns.log_level).upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )

    emit = None
    if ns.output == "jsonl":
        def _emit(ev: dict) -> None:
            if "ts" not in ev:
                ev = {**ev, "ts": time.time()}
            sys.stdout.write(json.dumps(ev, separators=(",", ":")) + "\n")
            sys.stdout.flush()

        emit = _emit

    try:
        if ns.cmd == "doctor":
            _doctor(ns, emit=emit)
            return 0

        if ns.cmd == "calibrate":
            cdp_host = getattr(ns, "cdp_host", None)
            cdp_port = getattr(ns, "cdp_port", None)
            if (cdp_host is None) ^ (cdp_port is None):
                raise SystemExit("--cdp-host and --cdp-port must be provided together")

            cfg = RunConfig(
                url="",
                selector="#calibrate-a",
                text=None,
                press_enter=False,
                # Force a headed session; calibration requires a GUI (we only read the mouse position).
                dry_run=False,
                timeout_s=float(getattr(ns, "timeout", 20.0)),
                browser_path=_path_or_none(getattr(ns, "browser_path", None)),
                browser_channel=str(getattr(ns, "browser_channel", default_browser_channel())),
                download_browser=bool(getattr(ns, "download_browser", default_download_browser())),
                sandbox=bool(getattr(ns, "sandbox", default_browser_sandbox())),
                browser_cache_dir=_path_or_none(getattr(ns, "browser_cache_dir", None)),
                cdp_host=(str(cdp_host) if cdp_host else None),
                cdp_port=(int(cdp_port) if cdp_port is not None else None),
                scale_x=1.0,
                scale_y=1.0,
                offset_x=0.0,
                offset_y=0.0,
                noise=Noise(x_px=0, y_px=0),
                mouse=MouseProfile(min_move_duration_s=0.0, max_move_duration_s=0.0),
                typing=TypingProfile(min_delay_s=0.0, max_delay_s=0.0),
                real_profile=_path_or_none(getattr(ns, "real_profile", None)),
                shim_profile=_path_or_none(getattr(ns, "shim_profile", None)),
                seed=None,
                pre_interact_delay_s=0.0,
                post_click_delay_s=0.0,
            )
            repo_root = Path(__file__).resolve().parents[2]
            write_path = _path_or_none(getattr(ns, "write_calibration", None))
            cal = asyncio.run(
                run_calibrate(
                    cfg,
                    repo_root=repo_root,
                    emit=emit,
                    write_path=write_path,
                )
            )

            if emit is None:
                # Human-friendly output (stdout), prompts already went to stderr.
                lines = [
                    "Calibration result",
                    f"scale_x:  {cal.scale_x:.6f}",
                    f"scale_y:  {cal.scale_y:.6f}",
                    f"offset_x: {cal.offset_x:.2f}",
                    f"offset_y: {cal.offset_y:.2f}",
                ]

                if write_path is not None:
                    lines.append(f"saved:    {write_path}")

                lines.extend(
                    [
                        "",
                        "Use with:",
                        "  gpt-web-driver run|demo|flow --calibration <file>",
                        "or pass explicit args:",
                        "  "
                        + " ".join(
                            [
                                "--scale-x",
                                f"{cal.scale_x:.6f}",
                                "--scale-y",
                                f"{cal.scale_y:.6f}",
                                "--offset-x",
                                f"{cal.offset_x:.2f}",
                                "--offset-y",
                                f"{cal.offset_y:.2f}",
                            ]
                        ),
                        "",
                        f"Recommended path: {default_calibration_path()}",
                    ]
                )
                sys.stdout.write(
                    "\n".join(lines) + "\n"
                )
            return 0

        cfg = _make_config(ns)

        if ns.cmd == "run":
            asyncio.run(
                run_single(
                    cfg,
                    emit=emit,
                    include_text_in_events=bool(ns.include_text_in_output),
                )
            )
            return 0

        if ns.cmd == "demo":
            repo_root = Path(__file__).resolve().parents[2]
            asyncio.run(
                run_demo(
                    cfg,
                    repo_root=repo_root,
                    emit=emit,
                    include_text_in_events=bool(ns.include_text_in_output),
                )
            )
            return 0

        if ns.cmd == "flow":
            spec = load_flow(Path(str(ns.flow)).expanduser())
            flow_vars = _parse_vars(getattr(ns, "var", None))
            # In text mode, keep stdout clean for the final result (avoid dry-run prints).
            emit_for_flow = emit if emit is not None else (lambda _ev: None)
            res = asyncio.run(
                run_flow(
                    cfg,
                    spec,
                    vars=flow_vars,
                    emit=emit_for_flow,
                    include_text_in_events=bool(ns.include_text_in_output),
                )
            )

            if emit is not None:
                emit({"event": "result", "value": res.value})
            else:
                sys.stdout.write((res.value or "") + "\n")
            return 0

        raise SystemExit(f"unknown command: {ns.cmd}")
    except Exception as e:
        if emit is not None:
            emit({"event": "error", "error": str(e), "error_type": e.__class__.__name__})
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
