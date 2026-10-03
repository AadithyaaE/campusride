"""Projecting points onto a route polyline (linear referencing).

A projection answers: *how far along the route is this point, and how far
off the route is it?* That pair (``distance_along_m``, ``offset_m``) is what
tracking, ETA, matching, deviation detection and recovery all build on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.geo.distance import LngLat, haversine_m
from app.geo.local_frame import LocalFrame

DEFAULT_PASSED_TOLERANCE_M = 15.0


@dataclass(frozen=True)
class Projection:
    distance_along_m: float
    """Distance from the start of the polyline to the snapped point."""
    offset_m: float
    """Distance from the input point to the snapped point (how far off-route)."""
    segment_index: int
    """Index ``i`` of the segment ``path[i] → path[i+1]`` containing the snapped point."""
    snapped: LngLat
    """The closest point on the polyline."""


def _validate(path: Sequence[LngLat], cum: Sequence[float]) -> None:
    if len(path) < 2:
        raise ValueError("polyline needs at least 2 points")
    if len(cum) != len(path):
        raise ValueError("cumulative distances must have one entry per point")


def _project_range(
    path: Sequence[LngLat],
    cum: Sequence[float],
    p: LngLat,
    lo: float,
    hi: float,
) -> Projection:
    """Closest point to ``p`` among polyline positions with ``lo <= d <= hi``."""
    frame = LocalFrame(p)
    best: Projection | None = None
    best_offset_sq = float("inf")

    for i in range(len(path) - 1):
        d0, d1 = cum[i], cum[i + 1]
        if d1 < lo or d0 > hi:
            continue
        seg_len = d1 - d0
        ax, ay = frame.to_xy(path[i])
        bx, by = frame.to_xy(path[i + 1])
        vx, vy = bx - ax, by - ay
        vv = vx * vx + vy * vy

        t = 0.0 if vv == 0.0 else -(ax * vx + ay * vy) / vv
        # Restrict t to the part of this segment inside the window.
        t_min = 0.0 if seg_len == 0 else max(0.0, (lo - d0) / seg_len)
        t_max = 1.0 if seg_len == 0 else min(1.0, (hi - d0) / seg_len)
        t = min(max(t, t_min), t_max)

        cx, cy = ax + t * vx, ay + t * vy
        offset_sq = cx * cx + cy * cy
        if offset_sq < best_offset_sq:  # strict: earliest segment wins ties
            best_offset_sq = offset_sq
            snapped = frame.to_lnglat(cx, cy)
            best = Projection(
                distance_along_m=d0 + t * seg_len,
                offset_m=haversine_m(p, snapped),
                segment_index=i,
                snapped=snapped,
            )

    if best is None:
        raise ValueError(f"window [{lo}, {hi}] does not overlap the polyline")
    return best


def project_point(path: Sequence[LngLat], cum: Sequence[float], p: LngLat) -> Projection:
    """Project ``p`` onto the whole polyline."""
    _validate(path, cum)
    return _project_range(path, cum, p, 0.0, cum[-1])


def project_point_windowed(
    path: Sequence[LngLat],
    cum: Sequence[float],
    p: LngLat,
    hint_d: float,
    back_m: float = 200.0,
    ahead_m: float = 2_000.0,
) -> Projection:
    """Project ``p`` but only onto ``[hint_d - back_m, hint_d + ahead_m]``.

    Tracking passes the bus's previous ``distance_along_m`` as the hint, so a
    route that crosses or doubles back on itself cannot snap the bus to the
    wrong pass of the same road.
    """
    _validate(path, cum)
    lo = max(0.0, hint_d - back_m)
    hi = min(cum[-1], hint_d + ahead_m)
    if lo > hi:
        lo = hi = min(max(hint_d, 0.0), cum[-1])
    return _project_range(path, cum, p, lo, hi)


def stop_distances(
    path: Sequence[LngLat],
    cum: Sequence[float],
    stops: Sequence[LngLat],
    *,
    max_offset_m: float | None = None,
) -> list[Projection]:
    """Project an *ordered* list of stops onto a route.

    Each stop is searched only from the previous stop's distance onwards, so
    the result is monotonic even on routes that revisit the same road.
    Raises ``ValueError`` if a stop is further than ``max_offset_m`` from the route.
    """
    _validate(path, cum)
    results: list[Projection] = []
    lo = 0.0
    for idx, stop in enumerate(stops):
        proj = _project_range(path, cum, stop, lo, cum[-1])
        if max_offset_m is not None and proj.offset_m > max_offset_m:
            raise ValueError(
                f"stop #{idx} at {stop} is {proj.offset_m:.1f} m off the route (max {max_offset_m} m)"
            )
        results.append(proj)
        lo = proj.distance_along_m
    return results


def has_passed(
    bus_distance_m: float,
    stop_distance_m: float,
    tolerance_m: float = DEFAULT_PASSED_TOLERANCE_M,
) -> bool:
    """True once the bus is clearly beyond the stop (beyond GPS jitter)."""
    return bus_distance_m > stop_distance_m + tolerance_m


def remaining_distance(bus_distance_m: float, stop_distance_m: float) -> float:
    """Distance along the route from the bus to the stop (0 if already there/past)."""
    return max(0.0, stop_distance_m - bus_distance_m)
