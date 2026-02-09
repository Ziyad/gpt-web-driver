from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from platformdirs import user_config_dir

from .demo_server import serve_directory
from .runner import FlowRunner, RunConfig


class CalibrationError(RuntimeError):
    pass


_CALIBRATE_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>gpt-web-driver calibration</title>
    <style>
      body { margin: 0; height: 100vh; overflow: hidden; background: #0b1220; color: rgba(255,255,255,0.92); font: 14px/1.4 ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; }
      .panel { position: fixed; left: 18px; top: 18px; max-width: 520px; padding: 14px 16px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.16); border-radius: 12px; }
      .panel h1 { margin: 0 0 8px 0; font-size: 16px; font-weight: 650; }
      .panel p { margin: 0; color: rgba(255,255,255,0.72); }
      .panel code { color: rgba(255,255,255,0.92); background: rgba(255,255,255,0.08); padding: 0 6px; border-radius: 6px; }
      .target { position: fixed; width: 92px; height: 92px; border-radius: 18px; border: 2px solid rgba(255,255,255,0.25); display: grid; place-items: center; user-select: none; }
      .target::before, .target::after { content: ""; position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); background: rgba(255,255,255,0.8); }
      .target::before { width: 56px; height: 2px; }
      .target::after { width: 2px; height: 56px; }
      .dot { position: absolute; left: 50%; top: 50%; width: 8px; height: 8px; transform: translate(-50%, -50%); border-radius: 999px; background: rgba(255,255,255,0.95); }
      #calibrate-a { left: 120px; top: 160px; background: rgba(77,163,255,0.22); }
      #calibrate-b { right: 120px; bottom: 120px; background: rgba(255,184,77,0.20); }
      .label { font-size: 18px; font-weight: 750; letter-spacing: 0.6px; }
    </style>
  </head>
  <body>
    <div class="panel">
      <h1>gpt-web-driver calibration</h1>
      <p>Put your mouse on the center dot inside <code>#calibrate-a</code> and <code>#calibrate-b</code>.</p>
    </div>
    <div id="calibrate-a" class="target"><div class="dot"></div><div class="label">A</div></div>
    <div id="calibrate-b" class="target"><div class="dot"></div><div class="label">B</div></div>
  </body>
</html>
"""


@dataclass(frozen=True)
class Calibration:
    scale_x: float
    scale_y: float
    offset_x: float
    offset_y: float

    @property
    def as_cli_args(self) -> list[str]:
        return [
            "--scale-x",
            str(self.scale_x),
            "--scale-y",
            str(self.scale_y),
            "--offset-x",
            str(self.offset_x),
            "--offset-y",
            str(self.offset_y),
        ]


def default_calibration_path() -> Path:
    """
    Default user config path for storing calibration.
    """
    return Path(user_config_dir("gpt-web-driver")) / "calibration.json"


def load_calibration(path: Path) -> Calibration:
    path = Path(path).expanduser()
    raw = path.read_text(encoding="utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise CalibrationError(f"calibration file must be a JSON object: {path}")

    # v1 schema: scale_x/scale_y/offset_x/offset_y plus optional metadata.
    for k in ("scale_x", "scale_y", "offset_x", "offset_y"):
        if k not in obj:
            raise CalibrationError(f"calibration file missing {k!r}: {path}")

    try:
        sx = float(obj["scale_x"])
        sy = float(obj["scale_y"])
        ox = float(obj["offset_x"])
        oy = float(obj["offset_y"])
    except Exception as e:
        raise CalibrationError(f"calibration values must be numbers: {path}") from e

    return Calibration(scale_x=sx, scale_y=sy, offset_x=ox, offset_y=oy)


def write_calibration(cal: Calibration, path: Path) -> None:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "scale_x": float(cal.scale_x),
        "scale_y": float(cal.scale_y),
        "offset_x": float(cal.offset_x),
        "offset_y": float(cal.offset_y),
        "created_at": int(time.time()),
        "platform": sys.platform,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _get_mouse_position() -> tuple[float, float]:
    """
    Returns current mouse cursor position in the same coordinate space used by pyautogui.moveTo().
    """
    try:
        import pyautogui  # type: ignore
    except ModuleNotFoundError as e:
        raise CalibrationError(
            "pyautogui is required for calibration. Install with: pip install 'gpt-web-driver[gui]'"
        ) from e

    p = pyautogui.position()
    # pyautogui returns a Point with x/y attributes on most platforms.
    x = float(getattr(p, "x", p[0]))
    y = float(getattr(p, "y", p[1]))
    return (x, y)


async def _wait_for_enter(prompt: str) -> None:
    # Keep prompts off stdout so users can redirect stdout cleanly (and jsonl stays valid).
    sys.stderr.write(prompt)
    if not prompt.endswith("\n"):
        sys.stderr.write("\n")
    sys.stderr.write("Press Enter to capture the current mouse position...\n")
    sys.stderr.flush()
    await asyncio.to_thread(sys.stdin.readline)


async def run_calibrate(
    config: RunConfig,
    *,
    repo_root: Path | None = None,
    emit: Callable[[dict[str, Any]], None] | None = None,
    write_path: Optional[Path] = None,
) -> Calibration:
    """
    Interactively calibrate a linear mapping:

        screen_x = viewport_x * scale_x + offset_x
        screen_y = viewport_y * scale_y + offset_y

    The calibration page provides two targets (A/B). We capture the OS mouse
    position for each target, and solve for scale and offset.
    """
    tmp: tempfile.TemporaryDirectory[str] | None = None

    web_root: Path | None = None
    if repo_root is not None:
        candidate = (Path(repo_root) / "webapp").resolve()
        if (candidate / "calibrate.html").exists():
            web_root = candidate

    # Fall back to an ephemeral page so `calibrate` also works from an installed package.
    if web_root is None:
        tmp = tempfile.TemporaryDirectory(prefix="gpt-web-driver-calibrate-")
        web_root = Path(tmp.name)
        (web_root / "calibrate.html").write_text(_CALIBRATE_HTML, encoding="utf-8")

    assert web_root is not None
    srv = serve_directory(web_root)
    try:
        url = f"{srv.base_url}/calibrate.html"
        if emit is not None:
            emit({"event": "calibrate.start", "url": url})

        async with FlowRunner(config, emit=emit) as runner:
            await runner.navigate(url)

            a = await runner.locate_point("#calibrate-a")
            b = await runner.locate_point("#calibrate-b")

            await _wait_for_enter(
                "Calibration point A:\n"
                "1) Focus the browser window\n"
                "2) Put your mouse cursor on the CENTER DOT inside the blue A target\n"
            )
            ax, ay = _get_mouse_position()

            await _wait_for_enter(
                "Calibration point B:\n"
                "1) Put your mouse cursor on the CENTER DOT inside the orange B target\n"
            )
            bx, by = _get_mouse_position()

        if emit is not None:
            emit(
                {
                    "event": "calibrate.point",
                    "point": "A",
                    "viewport_x": float(a.x),
                    "viewport_y": float(a.y),
                    "screen_x": float(ax),
                    "screen_y": float(ay),
                }
            )
            emit(
                {
                    "event": "calibrate.point",
                    "point": "B",
                    "viewport_x": float(b.x),
                    "viewport_y": float(b.y),
                    "screen_x": float(bx),
                    "screen_y": float(by),
                }
            )

        dx_v = float(b.x - a.x)
        dy_v = float(b.y - a.y)
        if dx_v == 0.0 or dy_v == 0.0:
            raise CalibrationError("Calibration points were degenerate (no delta). Try resizing the window and retry.")

        scale_x = float((bx - ax) / dx_v)
        scale_y = float((by - ay) / dy_v)
        offset_x = float(ax - scale_x * float(a.x))
        offset_y = float(ay - scale_y * float(a.y))

        cal = Calibration(scale_x=scale_x, scale_y=scale_y, offset_x=offset_x, offset_y=offset_y)
        if emit is not None:
            emit(
                {
                    "event": "calibrate.result",
                    "scale_x": float(cal.scale_x),
                    "scale_y": float(cal.scale_y),
                    "offset_x": float(cal.offset_x),
                    "offset_y": float(cal.offset_y),
                }
            )

        if write_path is not None:
            write_calibration(cal, Path(write_path))
            if emit is not None:
                emit({"event": "calibrate.write", "path": str(Path(write_path).expanduser())})
        return cal
    finally:
        srv.close()
        if tmp is not None:
            tmp.cleanup()
