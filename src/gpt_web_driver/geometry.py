from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Iterable, Sequence, Tuple


@dataclass(frozen=True)
class Noise:
    x_px: int = 12
    y_px: int = 5


def quad_center(quad: Sequence[float]) -> Tuple[float, float]:
    """
    Returns center (x, y) for a quad in [x1, y1, x2, y2, x3, y3, x4, y4] form.
    """
    if len(quad) < 8:
        raise ValueError("quad must have at least 8 numbers")
    xs = quad[0::2][:4]
    ys = quad[1::2][:4]
    return (sum(xs) / 4.0, sum(ys) / 4.0)


def rect_center(x: float, y: float, w: float, h: float) -> Tuple[float, float]:
    return (x + (w / 2.0), y + (h / 2.0))


def viewport_to_screen(
    viewport_x: float,
    viewport_y: float,
    *,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    offset_x: float,
    offset_y: float,
) -> Tuple[float, float]:
    return (viewport_x * scale_x + offset_x, viewport_y * scale_y + offset_y)


def apply_noise(
    screen_x: float,
    screen_y: float,
    *,
    noise: Noise,
    rng: random.Random | None = None,
) -> Tuple[float, float]:
    r = rng or random
    return (
        screen_x + r.randint(-noise.x_px, noise.x_px),
        screen_y + r.randint(-noise.y_px, noise.y_px),
    )

