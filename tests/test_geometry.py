import random

from spec2_hybrid.geometry import Noise, apply_noise, quad_center, rect_center, viewport_to_screen


def test_quad_center():
    quad = [0, 0, 10, 0, 10, 10, 0, 10]
    x, y = quad_center(quad)
    assert (x, y) == (5.0, 5.0)


def test_rect_center():
    assert rect_center(10, 20, 4, 6) == (12.0, 23.0)


def test_viewport_to_screen():
    assert viewport_to_screen(1.5, 2.5, offset_x=10, offset_y=20) == (11.5, 22.5)


def test_apply_noise_deterministic():
    rng = random.Random(0)
    x, y = apply_noise(100, 200, noise=Noise(x_px=3, y_px=2), rng=rng)
    assert (x, y) == (103, 201)
