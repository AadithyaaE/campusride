"""Live occupancy — the ONE occupancy rule (Feature 8). Pure functions, no I/O.

    occupancy = min(capacity, baseline + boarded)        while the trip is running
    occupancy = min(capacity, baseline)                  once the trip is completed

* ``baseline`` — the driver-reported headcount carried by telemetry. For simulated
  buses this is the simulator's SYNTHETIC per-stop headcount (riders who don't use
  the app); real device buses send none, so their baseline is 0.
* ``boarded`` — the number of QR boarding events recorded for the bus's CURRENT
  trip. It is always COUNTED from the boarding-event store (never incremented in
  memory), so re-polling, retries or simulator ticks can't change it.
* After the trip completes, QR riders have alighted at campus like everyone else.

``BusState.occupancy`` holds the result, so every existing API (``/buses``, stop
matching, ETA arrivals, bus comparison) shows the same number.
"""

from __future__ import annotations


def live_occupancy(*, baseline: int, boarded: int, capacity: int, trip_completed: bool) -> int:
    total = max(baseline, 0) + (0 if trip_completed else max(boarded, 0))
    return min(total, max(capacity, 0))


def available_seats(occupancy: int, capacity: int) -> int:
    """``max(capacity − occupancy, 0)``."""
    return max(capacity - max(occupancy, 0), 0)


def occupancy_percentage(occupancy: int, capacity: int) -> float | None:
    """``occupancy / capacity × 100``; None when capacity is unknown (0 or less)."""
    if capacity <= 0:
        return None
    return 100.0 * max(occupancy, 0) / capacity


def occupancy_percentage_display(occupancy: int, capacity: int) -> int | None:
    """Rounded percentage for display / APIs."""
    pct = occupancy_percentage(occupancy, capacity)
    return None if pct is None else round(pct)


def is_full(occupancy: int, capacity: int) -> bool:
    return available_seats(occupancy, capacity) == 0
