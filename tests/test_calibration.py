import json
from pathlib import Path

import pytest

from gpt_web_driver.calibration import Calibration, CalibrationError, load_calibration, write_calibration


def test_write_and_load_roundtrip(tmp_path: Path):
    p = tmp_path / "cal.json"
    cal = Calibration(scale_x=1.25, scale_y=1.5, offset_x=10.0, offset_y=20.0)
    write_calibration(cal, p)
    loaded = load_calibration(p)
    assert loaded == cal


def test_load_accepts_extra_metadata(tmp_path: Path):
    p = tmp_path / "cal.json"
    obj = {
        "version": 1,
        "scale_x": 2,
        "scale_y": 3,
        "offset_x": 4,
        "offset_y": 5,
        "created_at": 0,
        "platform": "win32",
    }
    p.write_text(json.dumps(obj), encoding="utf-8")
    loaded = load_calibration(p)
    assert loaded == Calibration(scale_x=2.0, scale_y=3.0, offset_x=4.0, offset_y=5.0)


def test_load_raises_on_missing_keys(tmp_path: Path):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps({"scale_x": 1}), encoding="utf-8")
    with pytest.raises(CalibrationError):
        load_calibration(p)

