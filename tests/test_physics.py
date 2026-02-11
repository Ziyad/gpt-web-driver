from __future__ import annotations

import asyncio
import math
import random

import pytest

from gpt_web_driver.core.physics import (
    CognitiveTyper,
    CognitiveTyperConfig,
    NeuromotorMouse,
    NeuromotorMouseConfig,
    _min_jerk_quintic,
    _min_jerk_quintic_vel,
)
from gpt_web_driver.os_input import MouseProfile, OsInput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeOsInput:
    """Minimal OsInput stand-in that records calls."""

    def __init__(self) -> None:
        self.moves: list[tuple[float, float]] = []
        self.clicks: list[None] = []
        self.keys_down: list[str] = []
        self.keys_up: list[str] = []
        self.chars: list[str] = []
        self._pos = (0.0, 0.0)

    def position(self) -> tuple[float, float]:
        return self._pos

    def move_to(self, x: float, y: float, *, profile: MouseProfile) -> None:
        self.moves.append((x, y))
        self._pos = (x, y)

    def click(self) -> None:
        self.clicks.append(None)

    def key_down(self, key: str) -> None:
        self.keys_down.append(key)

    def key_up(self, key: str) -> None:
        self.keys_up.append(key)

    def write_char(self, char: str) -> None:
        self.chars.append(char)


# ---------------------------------------------------------------------------
# _min_jerk_quintic
# ---------------------------------------------------------------------------


class TestMinJerkQuintic:
    def test_boundary_values(self):
        assert _min_jerk_quintic(0.0) == 0.0
        assert _min_jerk_quintic(1.0) == 1.0

    def test_midpoint(self):
        assert _min_jerk_quintic(0.5) == pytest.approx(0.5)

    def test_monotonic(self):
        prev = 0.0
        for i in range(1, 101):
            t = i / 100.0
            v = _min_jerk_quintic(t)
            assert v >= prev
            prev = v

    def test_clamped_below_zero(self):
        assert _min_jerk_quintic(-0.5) == 0.0

    def test_clamped_above_one(self):
        assert _min_jerk_quintic(1.5) == 1.0


class TestMinJerkQuinticVel:
    def test_endpoints_zero(self):
        assert _min_jerk_quintic_vel(0.0) == pytest.approx(0.0)
        assert _min_jerk_quintic_vel(1.0) == pytest.approx(0.0)

    def test_peak_around_midpoint(self):
        """Velocity should peak near t=0.5."""
        v_mid = _min_jerk_quintic_vel(0.5)
        v_quarter = _min_jerk_quintic_vel(0.25)
        v_three_quarter = _min_jerk_quintic_vel(0.75)
        assert v_mid > v_quarter
        assert v_mid > v_three_quarter


# ---------------------------------------------------------------------------
# NeuromotorMouse
# ---------------------------------------------------------------------------


class TestNeuromotorMouse:
    def _make(self, seed: int = 42) -> tuple[FakeOsInput, NeuromotorMouse]:
        fake = FakeOsInput()
        cfg = NeuromotorMouseConfig(
            sample_rate_hz=60.0, min_duration_s=0.01, max_duration_s=0.05
        )
        mouse = NeuromotorMouse(
            OsInput(dry_run=True),
            rng=random.Random(seed),
            cfg=cfg,
        )
        # Patch OS layer to use our fake
        mouse._os = fake
        return fake, mouse

    def test_move_reaches_target(self):
        fake, mouse = self._make()
        asyncio.run(mouse.move_to(500.0, 300.0))
        # Last recorded position should be near the target (within tremor range)
        last_x, last_y = fake.moves[-1]
        assert abs(last_x - 500.0) < 10.0
        assert abs(last_y - 300.0) < 10.0

    def test_move_generates_multiple_steps(self):
        fake = FakeOsInput()
        cfg = NeuromotorMouseConfig(
            sample_rate_hz=60.0, min_duration_s=0.01, max_duration_s=0.05
        )
        mouse = NeuromotorMouse(OsInput(dry_run=True), rng=random.Random(42), cfg=cfg)
        mouse._os = fake
        asyncio.run(mouse.move_to(800.0, 600.0, duration_s=0.05))
        assert len(fake.moves) >= 2

    def test_deterministic_with_seed(self):
        """Same seed produces same trajectory."""
        fake1, mouse1 = self._make(seed=99)
        asyncio.run(mouse1.move_to(300.0, 400.0))
        fake2, mouse2 = self._make(seed=99)
        asyncio.run(mouse2.move_to(300.0, 400.0))
        assert fake1.moves == fake2.moves

    def test_pink_noise_zero_mean(self):
        """Pink noise should be approximately zero-mean and unit-variance."""
        mouse = NeuromotorMouse(
            OsInput(dry_run=True),
            rng=random.Random(123),
        )
        samples = mouse._generate_pink_noise(500)
        mean = sum(samples) / len(samples)
        assert abs(mean) < 0.2  # should be near zero
        var = sum((s - mean) ** 2 for s in samples) / (len(samples) - 1)
        std = math.sqrt(var)
        assert 0.5 < std < 2.0  # roughly unit variance

    def test_pink_noise_fallback(self, monkeypatch):
        """Ensure the fallback (no numpy) path works."""
        # Force the numpy import to fail inside _generate_pink_noise
        mouse = NeuromotorMouse(
            OsInput(dry_run=True),
            rng=random.Random(77),
        )
        orig = mouse._generate_pink_noise

        def _no_numpy(n: int) -> list[float]:
            import builtins

            real_import = builtins.__import__

            def fake_import(name, *a, **kw):
                if name == "numpy":
                    raise ImportError("no numpy")
                return real_import(name, *a, **kw)

            monkeypatch.setattr(builtins, "__import__", fake_import)
            try:
                return orig(n)
            finally:
                monkeypatch.setattr(builtins, "__import__", real_import)

        samples = _no_numpy(200)
        assert len(samples) == 200
        mean = sum(samples) / len(samples)
        assert abs(mean) < 0.3


# ---------------------------------------------------------------------------
# CognitiveTyper
# ---------------------------------------------------------------------------


class TestCognitiveTyper:
    def _make(self, seed: int = 42) -> tuple[FakeOsInput, CognitiveTyper]:
        fake = FakeOsInput()
        typer = CognitiveTyper(
            OsInput(dry_run=True),
            rng=random.Random(seed),
            cfg=CognitiveTyperConfig(
                base_delay_s=0.0,
                dist_coeff_s=0.0,
                lognormal_scale_s=0.0,
                hold_s=0.0,
            ),
        )
        typer._os = fake
        return fake, typer

    def test_types_lowercase(self):
        fake, typer = self._make()
        asyncio.run(typer.type_text("abc"))
        assert "a" in fake.keys_down
        assert "b" in fake.keys_down
        assert "c" in fake.keys_down

    def test_types_uppercase_with_shift(self):
        fake, typer = self._make()
        asyncio.run(typer.type_text("A"))
        assert "shift" in fake.keys_down
        assert "a" in fake.keys_down

    def test_space_and_enter(self):
        fake, typer = self._make()
        asyncio.run(typer.type_text(" \n"))
        assert "space" in fake.keys_down
        assert "enter" in fake.keys_down

    def test_shifted_punctuation(self):
        fake, typer = self._make()
        asyncio.run(typer.type_text("!"))
        assert "shift" in fake.keys_down
        assert "1" in fake.keys_down

    def test_key_distance_calculation(self):
        typer = CognitiveTyper(OsInput(dry_run=True))
        # Same key -> zero distance
        assert typer._distance("a", "a") == 0.0
        # Adjacent keys on the same row
        d = typer._distance("a", "s")
        assert 0.5 < d < 1.5
        # Keys far apart
        d_far = typer._distance("a", "p")
        assert d_far > d

    def test_deterministic_with_seed(self):
        fake1, typer1 = self._make(seed=77)
        asyncio.run(typer1.type_text("hello"))
        fake2, typer2 = self._make(seed=77)
        asyncio.run(typer2.type_text("hello"))
        assert fake1.keys_down == fake2.keys_down

    def test_key_up_after_type(self):
        """All pressed keys should eventually be released."""
        fake, typer = self._make()
        asyncio.run(typer.type_text("hi"))
        # Every key_down should have a corresponding key_up
        for k in fake.keys_down:
            assert k in fake.keys_up
