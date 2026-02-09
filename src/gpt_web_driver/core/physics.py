from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass
from typing import Optional

from ..os_input import MouseProfile, OsInput


def _min_jerk_quintic(t: float) -> float:
    """
    Minimum-jerk position profile for t in [0, 1]:
        10 t^3 - 15 t^4 + 6 t^5
    """
    t = 0.0 if t <= 0.0 else (1.0 if t >= 1.0 else float(t))
    return (10.0 * t**3) - (15.0 * t**4) + (6.0 * t**5)


def _min_jerk_quintic_vel(t: float) -> float:
    """
    Derivative of minimum-jerk quintic (unnormalized):
        30 t^2 - 60 t^3 + 30 t^4
    """
    t = 0.0 if t <= 0.0 else (1.0 if t >= 1.0 else float(t))
    return (30.0 * t**2) - (60.0 * t**3) + (30.0 * t**4)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


@dataclass(frozen=True)
class NeuromotorMouseConfig:
    sample_rate_hz: float = 90.0
    min_duration_s: float = 0.18
    max_duration_s: float = 0.65
    # Tremor amplitude in pixels: base + vel_factor * vel_gain.
    tremor_base_px: float = 0.35
    tremor_vel_gain_px: float = 1.10


class NeuromotorMouse:
    """
    Human-ish mouse movement:
    - minimum-jerk quintic trajectory
    - pink-noise tremor scaled by instantaneous velocity profile
    """

    def __init__(
        self,
        os_input: OsInput,
        *,
        rng: Optional[random.Random] = None,
        cfg: NeuromotorMouseConfig | None = None,
    ) -> None:
        self._os = os_input
        self._rng = rng or random.Random()
        self._cfg = cfg or NeuromotorMouseConfig()

    def _generate_pink_noise(self, samples: int) -> list[float]:
        """
        1/f-ish noise using an FFT filter when numpy is available.
        Falls back to a simple low-pass filtered noise when numpy is missing.
        """
        n = max(2, int(samples))
        try:
            import numpy as np  # type: ignore

            seed = int(self._rng.getrandbits(32))
            np_rng = np.random.default_rng(seed)
            white = np_rng.standard_normal(n)
            f = np.fft.rfft(white)
            freqs = np.fft.rfftfreq(n)
            scale = np.ones_like(freqs)
            # Avoid div-by-zero; suppress DC component.
            scale[0] = 0.0
            # 1/sqrt(f) shaping yields ~1/f power spectrum.
            scale[1:] = 1.0 / np.sqrt(freqs[1:])
            f = f * scale
            pink = np.fft.irfft(f, n=n)
            pink = pink - float(np.mean(pink))
            std = float(np.std(pink)) or 1.0
            pink = pink / std
            return [float(x) for x in pink.tolist()]
        except Exception:
            # Fallback: leaky integrator (low-pass) over white noise.
            alpha = 0.92
            out: list[float] = []
            x = 0.0
            for _ in range(n):
                x = alpha * x + (1.0 - alpha) * self._rng.uniform(-1.0, 1.0)
                out.append(x)
            mean = sum(out) / len(out)
            out = [v - mean for v in out]
            var = sum(v * v for v in out) / max(1, len(out) - 1)
            std = math.sqrt(var) or 1.0
            return [v / std for v in out]

    async def move_to(self, target_x: float, target_y: float, *, duration_s: float | None = None) -> None:
        """
        Move the OS cursor to (target_x, target_y) along a minimum-jerk path.
        """
        sx, sy = self._os.position()

        dx = float(target_x) - float(sx)
        dy = float(target_y) - float(sy)
        dist = math.hypot(dx, dy)

        # Heuristic: longer moves take longer, but clamp to config bounds.
        base = _clamp(dist / 1400.0, 0.0, 1.0)
        est = self._cfg.min_duration_s + base * (self._cfg.max_duration_s - self._cfg.min_duration_s)
        dur = float(duration_s) if duration_s is not None else float(est * self._rng.uniform(0.85, 1.15))
        dur = _clamp(dur, self._cfg.min_duration_s, self._cfg.max_duration_s)

        hz = float(self._cfg.sample_rate_hz)
        steps = max(2, int(math.ceil(dur * hz)))
        dt = dur / float(steps - 1)

        noise_x = self._generate_pink_noise(steps)
        noise_y = self._generate_pink_noise(steps)
        step_profile = MouseProfile(min_move_duration_s=0.0, max_move_duration_s=0.0)

        # Normalize velocity profile peak for scaling tremor.
        # For the quintic, peak is around t ~= 0.5; compute a conservative max.
        vmax = max(_min_jerk_quintic_vel(i / (steps - 1)) for i in range(steps)) or 1.0

        for i in range(1, steps):
            t = float(i) / float(steps - 1)
            s = _min_jerk_quintic(t)
            vx = _min_jerk_quintic_vel(t) / vmax
            vel_factor = abs(float(vx))

            tremor = float(self._cfg.tremor_base_px + vel_factor * self._cfg.tremor_vel_gain_px)
            x = float(sx + dx * s + tremor * noise_x[i])
            y = float(sy + dy * s + tremor * noise_y[i])

            # Use duration=0 for stepwise control (pyautogui will still synthesize OS events).
            self._os.move_to(x, y, profile=step_profile)
            await asyncio.sleep(dt)


@dataclass(frozen=True)
class CognitiveTyperConfig:
    base_delay_s: float = 0.035
    dist_coeff_s: float = 0.008
    lognormal_sigma: float = 0.40
    lognormal_scale_s: float = 0.010
    # Hold keys long enough that some inter-key delays land before release (N-key rollover overlap),
    # but short enough to avoid OS key-repeat.
    hold_s: float = 0.055


class CognitiveTyper:
    """
    Human-ish typing:
    - key-to-key distance affects latency
    - log-normal jitter
    - N-key rollover via key hold + shorter inter-key delays (overlap occurs naturally)
    """

    # Rough US-QWERTY geometry in "key units".
    _ROWS = [
        ("`1234567890-=", 0.0),
        ("qwertyuiop[]\\", 0.5),
        ("asdfghjkl;'", 1.0),
        ("zxcvbnm,./", 1.5),
    ]

    _KEY_NAME = {
        "`": "grave",
        "-": "minus",
        "=": "equals",
        "[": "leftbracket",
        "]": "rightbracket",
        "\\": "backslash",
        ";": "semicolon",
        "'": "quote",
        ",": "comma",
        ".": "period",
        "/": "slash",
    }

    _SHIFTED = {
        "!": "1",
        "@": "2",
        "#": "3",
        "$": "4",
        "%": "5",
        "^": "6",
        "&": "7",
        "*": "8",
        "(": "9",
        ")": "0",
        "_": "-",
        "+": "=",
        "{": "[",
        "}": "]",
        "|": "\\",
        ":": ";",
        '"': "'",
        "<": ",",
        ">": ".",
        "?": "/",
        "~": "`",
    }

    def __init__(
        self,
        os_input: OsInput,
        *,
        rng: Optional[random.Random] = None,
        cfg: CognitiveTyperConfig | None = None,
    ) -> None:
        self._os = os_input
        self._rng = rng or random.Random()
        self._cfg = cfg or CognitiveTyperConfig()
        self._key_xy = self._build_key_xy()

    @classmethod
    def _build_key_xy(cls) -> dict[str, tuple[float, float]]:
        out: dict[str, tuple[float, float]] = {"space": (5.0, 4.0)}
        for row_idx, (keys, xoff) in enumerate(cls._ROWS):
            for col, ch in enumerate(keys):
                out[cls._KEY_NAME.get(ch, ch)] = (float(col) + float(xoff), float(row_idx))
        return out

    def _distance(self, a: str | None, b: str | None) -> float:
        if not a or not b:
            return 0.0
        pa = self._key_xy.get(a)
        pb = self._key_xy.get(b)
        if not pa or not pb:
            return 0.0
        return math.hypot(pa[0] - pb[0], pa[1] - pb[1])

    def _char_to_key(self, ch: str) -> tuple[list[str], str]:
        if ch == " ":
            return ([], "space")
        if ch == "\n":
            return ([], "enter")
        if "a" <= ch <= "z":
            return ([], ch)
        if "A" <= ch <= "Z":
            return (["shift"], ch.lower())
        if "0" <= ch <= "9":
            return ([], ch)
        if ch in self._SHIFTED:
            base = self._SHIFTED[ch]
            return (["shift"], self._KEY_NAME.get(base, base))
        # Unshifted punctuation that pyautogui understands as keys.
        if ch in self._KEY_NAME:
            return ([], self._KEY_NAME[ch])

        # Fall back to write_char for anything we can't reliably keyDown/keyUp.
        return ([], ch)

    async def type_text(self, text: str) -> None:
        pending: list[asyncio.Task[None]] = []

        async def _release_after(delay_s: float, keys: list[str]) -> None:
            try:
                await asyncio.sleep(float(delay_s))
            finally:
                for k in reversed(keys):
                    try:
                        self._os.key_up(k)
                    except Exception:
                        pass

        prev_key: str | None = None
        for ch in str(text):
            mods, key = self._char_to_key(ch)

            dist = self._distance(prev_key, key)
            jitter = float(self._rng.lognormvariate(0.0, float(self._cfg.lognormal_sigma))) * float(
                self._cfg.lognormal_scale_s
            )
            delay = float(self._cfg.base_delay_s + dist * self._cfg.dist_coeff_s + jitter)

            # Press modifiers first.
            for m in mods:
                self._os.key_down(m)

            # For unknown/surprising characters, fall back to pyautogui's write path.
            if (key not in self._key_xy) and key not in {"space", "enter"}:
                self._os.write_char(ch)
            else:
                self._os.key_down(key)
                # Natural overlap occurs when the next keyDown happens before this release.
                pending.append(asyncio.create_task(_release_after(self._cfg.hold_s, [key])))

            if mods:
                pending.append(asyncio.create_task(_release_after(self._cfg.hold_s, list(mods))))

            await asyncio.sleep(delay)
            prev_key = key

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
