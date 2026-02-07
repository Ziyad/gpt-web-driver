from __future__ import annotations

import json
from pathlib import Path

import pytest

from spec2_hybrid.browser import (
    BrowserNotFoundError,
    _cft_platform_key,
    default_browser_cache_dir,
    default_browser_channel,
    default_browser_sandbox,
    default_download_browser,
    is_wsl,
    resolve_browser_executable_path,
)


def test_default_browser_channel_env():
    assert default_browser_channel({"SPEC2_BROWSER_CHANNEL": "beta"}) == "beta"
    assert default_browser_channel({"SPEC2_BROWSER_CHANNEL": "  DEV  "}) == "dev"
    assert default_browser_channel({}) == "stable"


def test_default_download_browser_env():
    assert default_download_browser({}) is True
    assert default_download_browser({"SPEC2_BROWSER_DOWNLOAD": "0"}) is False
    assert default_download_browser({"SPEC2_BROWSER_DOWNLOAD": "true"}) is True


def test_default_browser_cache_dir_env(tmp_path: Path):
    d = default_browser_cache_dir({"SPEC2_BROWSER_CACHE_DIR": str(tmp_path)})
    assert d == tmp_path


def test_is_wsl_from_env():
    assert is_wsl({"WSL_DISTRO_NAME": "Ubuntu"}, proc_version="", osrelease="") is True
    assert is_wsl({"WSL_INTEROP": "1"}, proc_version="", osrelease="") is True


def test_is_wsl_from_proc_strings():
    assert is_wsl({}, proc_version="Linux version 6.6.0-microsoft-standard-WSL2", osrelease="") is True
    assert is_wsl({}, proc_version="", osrelease="6.6.0-microsoft-standard-WSL2") is True
    assert is_wsl({}, proc_version="Linux version 6.6.0-generic", osrelease="") is False


def test_default_browser_sandbox_env_override():
    assert default_browser_sandbox({"SPEC2_SANDBOX": "1"}) is True
    assert default_browser_sandbox({"SPEC2_SANDBOX": "0"}) is False
    assert default_browser_sandbox({"SPEC2_BROWSER_SANDBOX": "false"}) is False


def test_default_browser_sandbox_wsl_default():
    assert default_browser_sandbox({"WSL_DISTRO_NAME": "Ubuntu"}) is False


def test_resolve_browser_path_explicit(tmp_path: Path):
    exe = tmp_path / "chrome"
    exe.write_text("x", encoding="utf-8")
    assert (
        resolve_browser_executable_path(
            explicit_path=exe,
            download=False,
            channel="stable",
            cache_dir=tmp_path,
            env={},
            which=lambda _: None,
        )
        == exe
    )


def test_resolve_browser_path_env(tmp_path: Path):
    exe = tmp_path / "chrome"
    exe.write_text("x", encoding="utf-8")
    assert (
        resolve_browser_executable_path(
            explicit_path=None,
            download=False,
            channel="stable",
            cache_dir=tmp_path,
            env={"SPEC2_BROWSER_PATH": str(exe)},
            which=lambda _: None,
        )
        == exe
    )


def test_resolve_uses_installed_metadata(tmp_path: Path):
    exe = tmp_path / "downloaded-chrome"
    exe.write_text("x", encoding="utf-8")

    platform_key = _cft_platform_key(__import__("sys").platform, __import__("platform").machine())
    meta = tmp_path / "chrome-for-testing" / "stable" / platform_key / "installed.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    # Use proper JSON escaping for Windows paths (backslashes).
    meta.write_text(
        json.dumps(
            {
                "version": "0",
                "channel": "stable",
                "platform": platform_key,
                "executable_path": str(exe),
                "url": "",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    assert (
        resolve_browser_executable_path(
            explicit_path=None,
            download=False,
            channel="stable",
            cache_dir=tmp_path,
            env={},
            which=lambda _: None,
        )
        == exe
    )


def test_resolve_raises_when_download_disabled(tmp_path: Path):
    with pytest.raises(BrowserNotFoundError):
        resolve_browser_executable_path(
            explicit_path=None,
            download=False,
            channel="stable",
            cache_dir=tmp_path,
            env={},
            which=lambda _: None,
        )
