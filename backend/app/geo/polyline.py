"""Polyline construction, interpolation and derived shapes."""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.geo.distance import LngLat, bearing_deg, haversine_m
from app.geo.local_frame import LocalFrame
from app.geo.projection import Projection, project_point, project_point_windowed


@dataclass(frozen=True)
class PointOnLine:
    point: LngLat
    heading_deg: float
    """Direction of travel of the segment containing the point."""
    segment_index: int
    distance_along_m: float


def cumulative_distances(path: Sequence[LngLat]) -> list[float]:
    """Cumulative distance (m) at each vertex; first entry is 0, last is the length."""
    if not path:
        return []
    cum = [0.0]
    for a, b in zip(path, path[1:]):
        cum.append(cum[-1] + haversine_m(a, b))
    return cum


def interpolate_along(path: Sequence[LngLat], cum: Sequence[float], d: float) -> PointOnLine:
    """Point at distance ``d`` along the polyline (clamped to [0, length])."""
    if len(path) < 2 or len(cum) != len(path):
        raise ValueError("need >= 2 points and one cumulative distance per point")
    d = min(max(d, 0.0), cum[-1])
    i = min(max(bisect.bisect_right(cum, d) - 1, 0), len(path) - 2)
    # Skip forward over zero-length segments so the heading is meaningful.
    while i < len(path) - 2 and cum[i + 1] - cum[i] == 0.0:
        i += 1
    seg_len = cum[i + 1] - cum[i]
    t = 0.0 if seg_len == 0.0 else (d - cum[i]) / seg_len
    a, b = path[i], path[i + 1]
    point = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return PointOnLine(point=point, heading_deg=bearing_deg(a, b), segment_index=i, distance_along_m=d)


def _sub_path(path: Sequence[LngLat], cum: Sequence[float], from_d: float, to_d: float) -> list[LngLat]:
    """Vertices of the polyline between two distances, endpoints interpolated."""
    start = interpolate_along(path, cum, from_d).point
    end = interpolate_along(path, cum, to_d).point
    inner = [p for p, d in zip(path, cum) if from_d < d < to_d]
    return [start, *inner, end]


def offset_polyline(
    path: Sequence[LngLat],
    cum: Sequence[float],
    from_d: float,
    to_d: float,
    offset_m: float,
    taper_m: float | None = None,
    step_m: float = 25.0,
) -> list[LngLat]:
    """A path that leaves the route at ``from_d``, runs ``offset_m`` to the side
    and rejoins at ``to_d``. Positive offset = left of the direction of travel.

    The route is resampled every ``step_m`` (plus its own vertices) and the
    offset ramps linearly over ``taper_m`` at both ends (default: 20 % of the
    span), so the detour departs from and rejoins the route smoothly.
    Used by the simulator to synthesise route deviations.
    """
    if to_d <= from_d:
        raise ValueError("to_d must be greater than from_d")
    span = to_d - from_d
    taper = span * 0.2 if taper_m is None else min(taper_m, span / 2)
    n_steps = max(2, math.ceil(span / step_m))
    sample_d = sorted(
        {from_d + span * k / n_steps for k in range(n_steps + 1)} | {d for d in cum if from_d < d < to_d}
    )
    pts = [interpolate_along(path, cum, d).point for d in sample_d]
    frame = LocalFrame(pts[len(pts) // 2])
    xy = [frame.to_xy(p) for p in pts]
    sub_cum = cumulative_distances(pts)

    out: list[LngLat] = []
    for k, ((x, y), s) in enumerate(zip(xy, sub_cum)):
        # Direction at this vertex: from the previous vertex to the next one.
        px, py = xy[max(k - 1, 0)]
        nx, ny = xy[min(k + 1, len(xy) - 1)]
        dx, dy = nx - px, ny - py
        norm = math.hypot(dx, dy)
        if norm == 0.0:
            out.append(pts[k])
            continue
        lx, ly = -dy / norm, dx / norm  # left-hand normal
        ramp = 1.0 if taper == 0 else min(1.0, s / taper, (sub_cum[-1] - s) / taper)
        out.append(frame.to_lnglat(x + lx * offset_m * ramp, y + ly * offset_m * ramp))
    return out


def bbox(points: Iterable[LngLat]) -> tuple[float, float, float, float]:
    """(min_lng, min_lat, max_lng, max_lat)."""
    pts = list(points)
    if not pts:
        raise ValueError("bbox of no points")
    lngs = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return min(lngs), min(lats), max(lngs), max(lats)


@dataclass(frozen=True)
class Polyline:
    """Immutable polyline with precomputed cumulative distances."""

    coords: tuple[LngLat, ...]
    cum: tuple[float, ...]

    @classmethod
    def from_coords(cls, coords: Iterable[Sequence[float]]) -> Polyline:
        pts = tuple((float(c[0]), float(c[1])) for c in coords)
        if len(pts) < 2:
            raise ValueError("polyline needs at least 2 points")
        return cls(coords=pts, cum=tuple(cumulative_distances(pts)))

    @property
    def length_m(self) -> float:
        return self.cum[-1]

    def interpolate(self, d: float) -> PointOnLine:
        return interpolate_along(self.coords, self.cum, d)

    def project(self, p: LngLat) -> Projection:
        return project_point(self.coords, self.cum, p)

    def project_near(
        self, p: LngLat, hint_d: float, back_m: float = 200.0, ahead_m: float = 2_000.0
    ) -> Projection:
        return project_point_windowed(self.coords, self.cum, p, hint_d, back_m, ahead_m)

    def reversed(self) -> Polyline:
        """Same geometry travelled the other way.

        Distances satisfy ``d_reversed = length - d_original`` exactly, which is
        how evening (FROM_CAMPUS) variants reuse the morning geometry.
        """
        length = self.length_m
        return Polyline(
            coords=tuple(reversed(self.coords)),
            cum=tuple(length - c for c in reversed(self.cum)),
        )

    def slice(self, from_d: float, to_d: float) -> Polyline:
        if to_d <= from_d:
            raise ValueError("to_d must be greater than from_d")
        return Polyline.from_coords(_sub_path(self.coords, self.cum, from_d, to_d))
