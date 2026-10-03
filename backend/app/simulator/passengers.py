"""Deterministic SYNTHETIC occupancy (headcount after each stop of a trip).

Not real occupancy and not a prediction: QR boarding replaces this in Phase 5.
* TO_CAMPUS:   students board along the route, everyone alights at campus.
* FROM_CAMPUS: students board at campus, alight along the route.
"""

from __future__ import annotations

import random

from app.models.common import Direction


def occupancy_profile(rng: random.Random, n_stops: int, capacity: int, direction: Direction) -> list[int]:
    """Occupancy after visiting each stop index 0..n-1 (last is always 0)."""
    if n_stops < 2:
        return [0] * n_stops
    load = round(capacity * rng.uniform(0.55, 0.95))
    weights = [rng.uniform(0.5, 1.5) for _ in range(n_stops - 1)]
    total = sum(weights)
    cumulative: list[int] = []
    acc = 0.0
    for w in weights:
        acc += w
        cumulative.append(round(load * acc / total))
    if direction is Direction.TO_CAMPUS:
        return [*cumulative, 0]  # boarding at stops 0..n-2, all alight at campus
    # FROM_CAMPUS: full at campus (stop 0), then decreasing as students alight
    return [load] + [load - c for c in cumulative[:-1]] + [0]
