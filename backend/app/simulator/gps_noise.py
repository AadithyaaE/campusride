"""Deterministic GPS jitter so synthetic fixes look like a phone, not a ruler."""

from __future__ import annotations

import random

from app.geo import LngLat, LocalFrame


def jitter(point: LngLat, sigma_m: float, rng: random.Random) -> tuple[LngLat, float]:
    """Gaussian offset (σ metres per axis). Returns (noisy point, reported accuracy_m)."""
    if sigma_m <= 0:
        return point, 3.0
    frame = LocalFrame(point)
    noisy = frame.to_lnglat(rng.gauss(0.0, sigma_m), rng.gauss(0.0, sigma_m))
    return noisy, round(sigma_m * 1.5, 1)
