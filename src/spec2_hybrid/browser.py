from __future__ import annotations

import json
import os
import platform as _platform
import shutil
import stat
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

_CFT_LKG_DOWNLOADS_JSON_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
)


class BrowserNotFoundError(RuntimeError):
    pass


def default_browser_channel(env: Mapping[str, str] = os.environ) -> str:
    """
    Which Chrome-for-Testing channel to install when auto-downloading.

    Values: stable, beta, dev, canary
    """
    v = (env.get("SPEC2_BROWSER_CHANNEL") or "stable").strip().lower()
    return v or "stable"


def default_download_browser(env: Mapping[str, str] = os.environ) -> bool:
    """
    Whether `gpt-web-driver` should auto-download a browser when none is found.
    """
    override = env.get("SPEC2_BROWSER_DOWNLOAD")
    if override is None:
        return True
    return override.strip().lower() in {"1", "true", "yes", "y", "on"}


def is_wsl(env: Mapping[str, str] = os.environ, *, proc_version: str | None = None, osrelease: str | None = None) -> bool:
    """
    Best-effort WSL detection.
    """
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return True

    def _read(path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    v = proc_version if proc_version is not None else _read("/proc/version")
    r = osrelease if osrelease is not None else _read("/proc/sys/kernel/osrelease")
    blob = f"{v}\n{r}".lower()
    return "microsoft" in blob or "wsl" in blob


def default_browser_sandbox(env: Mapping[str, str] = os.environ) -> bool:
    """
    Whether to run Chrome with its sandbox enabled.

    On WSL, Chrome-for-Testing often requires `--no-sandbox`, so the default is
    disabled there unless overridden.
    """
    override = env.get("SPEC2_SANDBOX")
    if override is None:
        override = env.get("SPEC2_BROWSER_SANDBOX")

    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "y", "on"}

    if is_wsl(env):
        return False

    return True


def default_browser_cache_dir(env: Mapping[str, str] = os.environ) -> Path:
    """
    Base cache dir for browser downloads.
    """
    override = (env.get("SPEC2_BROWSER_CACHE_DIR") or "").strip()
    if override:
        return Path(override).expanduser()

    xdg = (env.get("XDG_CACHE_HOME") or "").strip()
    if xdg:
        return Path(xdg).expanduser() / "gpt-web-driver"

    return Path.home() / ".cache" / "gpt-web-driver"


def _cft_platform_key(sys_platform: str, machine: str) -> str:
    sys_platform = sys_platform.lower()
    machine = machine.lower()

    if sys_platform.startswith("linux"):
        if machine in {"x86_64", "amd64"}:
            return "linux64"
        raise BrowserNotFoundError(f"Unsupported Linux architecture for Chrome download: {machine}")

    # sys.platform on Windows is usually "win32" even for 64-bit Python.
    if sys_platform.startswith("win"):
        if machine in {"amd64", "x86_64"}:
            return "win64"
        return "win32"

    if sys_platform == "darwin":
        if machine in {"x86_64", "amd64"}:
            return "mac-x64"
        if machine in {"arm64", "aarch64"}:
            return "mac-arm64"
        raise BrowserNotFoundError(f"Unsupported macOS architecture for Chrome download: {machine}")

    raise BrowserNotFoundError(f"Unsupported platform for Chrome download: {sys_platform}")


def _cft_channel_key(channel: str) -> str:
    c = channel.strip().lower()
    mapping = {
        "stable": "Stable",
        "beta": "Beta",
        "dev": "Dev",
        "canary": "Canary",
    }
    if c not in mapping:
        raise ValueError(f"Unknown browser channel: {channel!r} (expected one of: stable, beta, dev, canary)")
    return mapping[c]


def _validate_executable_path(path: Path) -> Path:
    path = path.expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Browser executable does not exist: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Browser path is not a file: {path}")
    return path


def _find_system_browser(which: Callable[[str], Optional[str]] = shutil.which) -> Optional[Path]:
    # Prefer Chrome names over Chromium, since nodriver is generally tested against Chrome.
    candidates = [
        "google-chrome-stable",
        "google-chrome",
        "chromium",
        "chromium-browser",
        "chrome",
        "Google Chrome",
    ]
    for name in candidates:
        p = which(name)
        if p:
            return Path(p)
    return None


@dataclass(frozen=True)
class InstalledBrowser:
    version: str
    channel: str
    platform: str
    executable_path: Path
    url: str


def _installed_metadata_path(*, cache_dir: Path, channel: str, platform_key: str) -> Path:
    return cache_dir / "chrome-for-testing" / channel / platform_key / "installed.json"


def _read_installed_browser(meta_path: Path) -> Optional[InstalledBrowser]:
    if not meta_path.exists():
        return None
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    exe = Path(data["executable_path"])
    if not exe.exists():
        return None
    return InstalledBrowser(
        version=str(data["version"]),
        channel=str(data["channel"]),
        platform=str(data["platform"]),
        executable_path=exe,
        url=str(data.get("url") or ""),
    )


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "gpt-web-driver"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def _download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "gpt-web-driver"})
    with urllib.request.urlopen(req, timeout=300) as resp, dest.open("wb") as f:
        shutil.copyfileobj(resp, f)


def _safe_extract_zip(zip_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_abs = dest_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                raise RuntimeError(f"Refusing to extract suspicious zip path: {name!r}")

            out_path = (dest_dir / name).resolve()
            if not out_path.is_relative_to(dest_abs):
                raise RuntimeError(f"Refusing to extract zip member outside target dir: {name!r}")

            if info.is_dir():
                out_path.mkdir(parents=True, exist_ok=True)
                continue

            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def _cft_extract_root_dir(platform_key: str) -> str:
    mapping = {
        "linux64": "chrome-linux64",
        "mac-x64": "chrome-mac-x64",
        "mac-arm64": "chrome-mac-arm64",
        "win64": "chrome-win64",
        "win32": "chrome-win32",
    }
    if platform_key not in mapping:
        raise BrowserNotFoundError(f"Unsupported Chrome-for-Testing platform key: {platform_key}")
    return mapping[platform_key]


def _find_cft_executable(extract_dir: Path, platform_key: str) -> Path:
    root = extract_dir / _cft_extract_root_dir(platform_key)
    if platform_key.startswith("linux"):
        return root / "chrome"
    if platform_key.startswith("win"):
        return root / "chrome.exe"
    if platform_key.startswith("mac"):
        # Common layout for Chrome-for-Testing zips:
        #   chrome-mac-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
        candidates = [
            root / "Google Chrome for Testing.app" / "Contents" / "MacOS" / "Google Chrome for Testing",
            # Fallbacks for potential packaging differences.
            root / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome",
            root / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    raise BrowserNotFoundError(f"Unsupported platform key: {platform_key}")


def _ensure_executable_bit(path: Path) -> None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return
    mode = st.st_mode
    if mode & stat.S_IXUSR:
        return
    try:
        path.chmod(mode | stat.S_IXUSR)
    except Exception:
        return


def ensure_chrome_for_testing(
    *,
    channel: str,
    cache_dir: Path,
    platform_key: str,
    force: bool = False,
) -> Path:
    """
    Ensure a Chrome-for-Testing browser exists locally and return its executable path.
    """
    channel = channel.strip().lower()
    base = cache_dir / "chrome-for-testing" / channel / platform_key
    meta_path = _installed_metadata_path(cache_dir=cache_dir, channel=channel, platform_key=platform_key)

    if not force:
        installed = _read_installed_browser(meta_path)
        if installed is not None:
            return installed.executable_path

    print(f"[browser] Resolving Chrome-for-Testing ({channel}/{platform_key})")
    data = _fetch_json(_CFT_LKG_DOWNLOADS_JSON_URL)
    ch = data["channels"][_cft_channel_key(channel)]
    version = str(ch["version"])

    downloads = ch["downloads"]["chrome"]
    url = None
    for d in downloads:
        if d.get("platform") == platform_key:
            url = d.get("url")
            break
    if not url:
        raise BrowserNotFoundError(f"No Chrome-for-Testing download found for platform={platform_key!r}")

    version_dir = base / version
    expected_exe = _find_cft_executable(version_dir, platform_key)
    if expected_exe.exists() and not force:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(
                {
                    "version": version,
                    "channel": channel,
                    "platform": platform_key,
                    "executable_path": str(expected_exe),
                    "url": url,
                    "installed_at": int(time.time()),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return expected_exe

    staging = base / f".staging-{version}-{os.getpid()}-{int(time.time())}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        archive = staging / "chrome.zip"
        extract = staging / "extract"
        print(f"[browser] Downloading {url}")
        _download_file(url, archive)
        print("[browser] Extracting...")
        _safe_extract_zip(archive, extract)

        exe = _find_cft_executable(extract, platform_key)
        if not exe.exists():
            raise BrowserNotFoundError(
                "Downloaded Chrome-for-Testing archive did not contain an expected executable at: "
                f"{exe} (platform={platform_key})"
            )

        if version_dir.exists():
            shutil.rmtree(version_dir, ignore_errors=True)
        version_dir.parent.mkdir(parents=True, exist_ok=True)
        extract.rename(version_dir)

        exe = _find_cft_executable(version_dir, platform_key)
        _ensure_executable_bit(exe)

        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(
                {
                    "version": version,
                    "channel": channel,
                    "platform": platform_key,
                    "executable_path": str(exe),
                    "url": url,
                    "installed_at": int(time.time()),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"[browser] Installed: {exe}")
        return exe
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def resolve_browser_executable_path(
    *,
    explicit_path: Optional[Path],
    download: bool,
    channel: str,
    cache_dir: Optional[Path] = None,
    env: Mapping[str, str] = os.environ,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> Path:
    """
    Resolve a browser executable path suitable for passing to nodriver.

    Resolution order:
    1) explicit_path (CLI)
    2) SPEC2_BROWSER_PATH
    3) previously installed Chrome-for-Testing in cache
    4) system browser in PATH
    5) auto-download Chrome-for-Testing (if enabled)
    """
    if explicit_path is not None:
        return _validate_executable_path(explicit_path)

    env_path = (env.get("SPEC2_BROWSER_PATH") or "").strip()
    if env_path:
        return _validate_executable_path(Path(env_path))

    cache = cache_dir or default_browser_cache_dir(env)
    platform_key = _cft_platform_key(sys.platform, _platform.machine())
    meta_path = _installed_metadata_path(cache_dir=cache, channel=channel.strip().lower(), platform_key=platform_key)
    installed = _read_installed_browser(meta_path)
    if installed is not None:
        return installed.executable_path

    sys_browser = _find_system_browser(which=which)
    if sys_browser is not None:
        return sys_browser

    if not download:
        raise BrowserNotFoundError(
            "Could not find a Chrome/Chromium browser binary. Either install one on the system, or pass "
            "`--browser-path /path/to/chrome` (or set SPEC2_BROWSER_PATH). You can also enable auto-download "
            "with `--download-browser` / SPEC2_BROWSER_DOWNLOAD=1."
        )

    exe = ensure_chrome_for_testing(
        channel=channel,
        cache_dir=cache,
        platform_key=platform_key,
    )
    return _validate_executable_path(exe)
