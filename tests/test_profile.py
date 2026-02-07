from pathlib import Path

import pytest

from spec2_hybrid.profile import ProfileConfig, ensure_profile


def test_ensure_profile_copies_and_excludes_cache(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "Cookies").write_text("cookie", encoding="utf-8")

    cache_dir = real / "Cache"
    cache_dir.mkdir()
    (cache_dir / "big.bin").write_text("x", encoding="utf-8")

    shim = tmp_path / "shim"
    ensure_profile(ProfileConfig(real_profile_dir=real, shim_profile_dir=shim, exclude_globs=("Cache*",)))

    assert (shim / "Cookies").exists()
    assert not (shim / "Cache").exists()


def test_ensure_profile_requires_real_dir(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        ensure_profile(ProfileConfig(real_profile_dir=tmp_path / "missing", shim_profile_dir=tmp_path / "shim"))

