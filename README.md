# gpt-web-driver

Hybrid browser automation that splits the world into:

- **Read (CDP):** use `nodriver` to launch/connect to Chrome and *passively* read DOM state/geometry.
- **Write (OS):** use **OS-level** input (`pyautogui`) for mouse + keyboard so the page sees trusted input events.

This is intentionally "headed" automation. If you are running without a GUI (CI, containers, plain WSL without WSLg), use `--dry-run`.

## How It Works

At a high level, `gpt-web-driver` runs a single flow:

1. Start a Chromium browser via `nodriver` (or connect via CDP).
2. Navigate to a URL.
3. Wait for a CSS selector to exist (CDP DOM polling; avoids driver flakiness).
4. Compute a viewport point for the element:
   - Prefer element handle helpers when present (`bounding_box` / `quads`).
   - Fall back to CDP `DOM.getBoxModel` (+ `Page.getLayoutMetrics` for scroll offsets).
5. Convert viewport coords to screen coords using `--offset-x/--offset-y`, inject optional noise, then:
6. Move the real mouse + click + type using `pyautogui` (unless `--dry-run`).

### CDP Hardening ("Stealth")

After navigation, `gpt-web-driver` best-effort disables noisy domains:

- `Runtime`
- `Log`
- `Debugger`

This is intended to reduce overhead and avoid some anti-debugger tricks. The implementation lives in `src/spec2_hybrid/stealth.py`.

## Requirements

- Python 3.12+ (see `pyproject.toml`)
- A Chromium-based browser available for `nodriver` to launch (or allow `gpt-web-driver` to auto-download one)
- A real GUI session if you plan to do OS-level input (`--no-dry-run`)

## Install

If you want real OS-level input (`--no-dry-run`), run `gpt-web-driver` on the same OS session as the browser. For most people on a Windows machine, that means: run it directly on Windows (not WSL).

### Windows (Recommended)

Create a virtualenv and install the package (PowerShell):

```powershell
py -3.12 -m venv .venv   # (or 3.13+)
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Or use the helper script:

```powershell
.\scripts\windows\bootstrap.ps1 -PyVersion 3.13
```

If PowerShell blocks activation scripts, either:

- run: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
- or activate via `cmd.exe`: `.venv\Scripts\activate.bat`

### Linux/macOS/WSL

Create a virtualenv and install the package:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

If you only want runtime deps (no tests):

```bash
python -m pip install -e .
```

## CLI

Show help:

```bash
gpt-web-driver --help
# or
python -m spec2_hybrid --help
```

## Quickstart: Local Deterministic Test Page

This repo includes a tiny local test app (`webapp/`) with a stable input field `#fname`.

Terminal 1 (serve the page; fixed port makes commands repeatable):

```powershell
.\.venv\Scripts\python.exe .\scripts\serve_test_app.py --host 127.0.0.1 --port 6767
```

Terminal 2 (real OS input):

```powershell
gpt-web-driver run --url "http://127.0.0.1:6767/index.html" --selector "#fname" --text "Hello" --no-dry-run
```

Dry-run (safe; prints intended actions without moving the mouse):

```powershell
gpt-web-driver run --url "http://127.0.0.1:6767/index.html" --selector "#fname" --text "Hello" --dry-run
```

Run the local demo (serves `sample-body.html` over HTTP and runs a single browser session):

```bash
gpt-web-driver demo --dry-run
```

### Use A Windows Host Browser From WSL (CDP)

If you want to avoid running a Linux browser inside WSL, you can connect to a debuggable Chrome running on Windows via CDP.

1) Start Chrome on Windows with a remote debugging port (use a dedicated profile dir):

```powershell
& "$env:ProgramFiles\\Google\\Chrome\\Application\\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$env:TEMP\\gpt-web-driver-cdp"
```

2) From WSL, connect to it:

```bash
gpt-web-driver demo --dry-run --cdp-host 127.0.0.1 --cdp-port 9222
```

Note: OS-level input from WSL cannot control Windows mouse/keyboard. This mode is therefore most useful with `--dry-run` (DOM reads + printed intended actions). For real OS input on Windows, run `gpt-web-driver` with a Windows Python install.

Run against an arbitrary URL/selector:

```bash
gpt-web-driver run --url http://127.0.0.1:6767 --selector "#prompt-textarea" --text "Hello" --dry-run
```

Note: `demo` is meant to be run from a repo checkout (it serves `sample-body.html` from the repo).

### Safety toggles

- `--dry-run`: does not import or call `pyautogui`; prints intended OS actions instead. Use this in containers/CI.
- `--no-dry-run`: force OS-level input even if auto-detection would default to dry-run.

You can also override the default with `SPEC2_DRY_RUN=1`.

### Browser selection / auto-download

If no system Chrome/Chromium is found, `gpt-web-driver` can automatically download **Chrome for Testing**
into your cache directory and launch it via `nodriver`.

- `--browser-path /path/to/chrome` (or `SPEC2_BROWSER_PATH=/path/to/chrome`): use an explicit browser.
- `--no-download-browser` (or `SPEC2_BROWSER_DOWNLOAD=0`): disable auto-download.
- `--browser-channel stable|beta|dev|canary` (or `SPEC2_BROWSER_CHANNEL=...`): choose which channel to download.
- `--browser-cache-dir /some/dir` (or `SPEC2_BROWSER_CACHE_DIR=...`): override where downloads are stored.
- `--no-sandbox` (or `SPEC2_SANDBOX=0`): disable the Chrome sandbox (often required on WSL/container environments).

### Calibration

Viewport coordinates returned by CDP are translated to screen coordinates by adding configurable offsets:

- `--offset-x`
- `--offset-y`

Defaults are conservative and typically require manual tuning, depending on OS theme, window decorations, DPI scaling, and monitor layout.

Other knobs:

- `--timeout` (seconds): wait budget for the selector to exist
- `--noise-x/--noise-y`: random jitter (pixels) applied to the final screen coordinate
- `--move-min/--move-max`: mouse move duration range (seconds)
- `--type-min/--type-max`: per-character typing delay range (seconds)
- `--no-enter`: do not press Enter after typing

### Profile shim (optional)

If you want to reuse cookies/auth without locking your real Chrome profile, you can opt-in to cloning a real profile into a shim directory:

- `--real-profile`
- `--shim-profile`

Cache directories are excluded to keep the clone smaller.

## Testing

Unit tests avoid requiring a GUI by:

- mocking `pyautogui`
- injecting a fake `nodriver` module into `stealth_init`

Run:

```bash
python -m pytest
```

## Ubuntu on WSL notes

OS-level input requires a GUI display. On Windows 11, WSLg typically "just works". Quick sanity checks:

```bash
echo "$WAYLAND_DISPLAY"
echo "$DISPLAY"
```

If you plan to run with `--no-dry-run`, you may also need extra system packages for `pyautogui` on Ubuntu:

```bash
sudo apt update
sudo apt install -y python3-tk python3-dev scrot
```

If you do not have a GUI in WSL, stick to `--dry-run` (and/or set `SPEC2_DRY_RUN=1`) so your flow can still be exercised without moving the real mouse/keyboard.

## Troubleshooting

- `No module named pytest`: install dev deps: `python -m pip install -e ".[dev]"`.
- `pyautogui` fails to import / complains about display: run with `--dry-run` or ensure you have a GUI session.
- Clicks land in the wrong place: tune `--offset-x/--offset-y` and consider maximizing the window.
- `could not find a valid chrome browser binary`: either install Chrome/Chromium, pass `--browser-path`, or allow auto-download (default).
