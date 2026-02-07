# spec2-hybrid

Hybrid browser automation prototype per `spec2.md`:

- `nodriver` is used only for passive DOM reads (finding nodes, waiting for selectors, reading geometry).
- All user interaction is performed via OS-level input (`pyautogui`) to generate trusted OS events.
- CDP hardening disables `Runtime`, `Log`, and `Debugger` domains as early as possible.

This is intentionally "headed" automation. If you are running without a GUI (CI, containers, plain WSL without WSLg), use `--dry-run`.

## Requirements

- Python 3.12+ (see `pyproject.toml`)
- A Chromium-based browser available for `nodriver` to launch (or allow `spec2-hybrid` to auto-download one)
- A real GUI session if you plan to do OS-level input (`--no-dry-run`)

## Install

If you want real OS-level input (`--no-dry-run`), run `spec2-hybrid` on the same OS session as the browser. For most people on a Windows machine, that means: run it directly on Windows (not WSL).

### Windows (Recommended)

Create a virtualenv and install the package (PowerShell):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Or use the helper script:

```powershell
.\scripts\windows\bootstrap.ps1
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
spec2-hybrid --help
# or
python -m spec2_hybrid --help
```

Run the local demo (serves `sample-body.html` over HTTP and runs a single browser session):

```bash
spec2-hybrid demo --dry-run
```

### Use A Windows Host Browser From WSL (CDP)

If you want to avoid running a Linux browser inside WSL, you can connect to a debuggable Chrome running on Windows via CDP.

1) Start Chrome on Windows with a remote debugging port (use a dedicated profile dir):

```powershell
& "$env:ProgramFiles\\Google\\Chrome\\Application\\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$env:TEMP\\spec2-hybrid-cdp"
```

2) From WSL, connect to it:

```bash
spec2-hybrid demo --dry-run --cdp-host 127.0.0.1 --cdp-port 9222
```

Note: OS-level input from WSL cannot control Windows mouse/keyboard. This mode is therefore most useful with `--dry-run` (DOM reads + printed intended actions). For real OS input on Windows, run `spec2-hybrid` with a Windows Python install.

Run against an arbitrary URL/selector:

```bash
spec2-hybrid run --url http://127.0.0.1:6767 --selector "#prompt-textarea" --text "Hello" --dry-run
```

Note: `demo` is meant to be run from a repo checkout (it serves `sample-body.html` from the repo).

### Safety toggles

- `--dry-run`: does not import or call `pyautogui`; prints intended OS actions instead. Use this in containers/CI.
- `--no-dry-run`: force OS-level input even if auto-detection would default to dry-run.

You can also override the default with `SPEC2_DRY_RUN=1`.

### Browser selection / auto-download

If no system Chrome/Chromium is found, `spec2-hybrid` can automatically download **Chrome for Testing**
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
