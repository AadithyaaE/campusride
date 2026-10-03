"""Physical routes and their directions.

A ``Route`` is one physical road path (``R1``) stored ONCE, in the
TO_CAMPUS orientation. It has two ``RouteDirection`` variants:

* ``R1``   — TO_CAMPUS   (morning; travels the stored path forwards)
* ``R1-E`` — FROM_CAMPUS (evening; travels the same path in reverse)

Each variant lists its stops in travel order with distances measured in
*its own* frame, so for every stop ``d_from_campus = length_m - d_to_campus``.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field, PrivateAttr, model_validator

from app.geo import Polyline
from app.models.common import Direction, Document, LineString, SegmentClass

HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


class RouteStop(BaseModel):
    stop_id: str
    seq: int = Field(ge=0)
    distance_along_m: float = Field(ge=0)
    scheduled_offset_s: int = Field(ge=0)
    """Scheduled arrival, seconds after the trip's scheduled start."""
    dwell_s: int = Field(ge=0)


class RouteDirection(BaseModel):
    variant_id: str
    direction: Direction
    label: str
    """User-facing, e.g. ``R1 — To Campus``."""
    stops: list[RouteStop]

    @model_validator(mode="after")
    def _ordered(self) -> RouteDirection:
        if len(self.stops) < 2:
            raise ValueError(f"{self.variant_id}: a route direction needs at least 2 stops")
        for i, s in enumerate(self.stops):
            if s.seq != i:
                raise ValueError(f"{self.variant_id}: stop seq must be 0..n-1 in order")
        for a, b in zip(self.stops, self.stops[1:]):
            if b.distance_along_m < a.distance_along_m:
                raise ValueError(
                    f"{self.variant_id}: stop distances must not decrease ({a.stop_id}→{b.stop_id})"
                )
            if b.scheduled_offset_s < a.scheduled_offset_s:
                raise ValueError(f"{self.variant_id}: scheduled offsets must not decrease")
        if len({s.stop_id for s in self.stops}) != len(self.stops):
            raise ValueError(f"{self.variant_id}: a stop may appear only once per direction")
        return self

    @property
    def stop_ids(self) -> list[str]:
        return [s.stop_id for s in self.stops]

    def stop(self, stop_id: str) -> RouteStop | None:
        return next((s for s in self.stops if s.stop_id == stop_id), None)


class Route(Document):
    name: str
    color: str = Field(pattern=HEX_COLOR)
    campus_id: str
    path: LineString
    """Canonical geometry in the TO_CAMPUS orientation."""
    cum_dist_m: list[float]
    segment_classes: list[SegmentClass]
    """One road class per path segment (``len(path) - 1``), TO_CAMPUS order."""
    length_m: float = Field(gt=0)
    directions: list[RouteDirection]
    active: bool = True

    _polylines: dict[Direction, Polyline] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self) -> Route:
        n = len(self.path.coordinates)
        if len(self.cum_dist_m) != n:
            raise ValueError(f"{self.id}: cum_dist_m needs one entry per path point")
        if len(self.segment_classes) != n - 1:
            raise ValueError(f"{self.id}: segment_classes needs one entry per path segment")
        if not math.isclose(self.cum_dist_m[-1], self.length_m, abs_tol=0.5):
            raise ValueError(f"{self.id}: length_m does not match cum_dist_m")
        dirs = [d.direction for d in self.directions]
        if sorted(dirs) != sorted(Direction):
            raise ValueError(f"{self.id}: needs exactly one TO_CAMPUS and one FROM_CAMPUS direction")
        for d in self.directions:
            if d.stops[-1].distance_along_m > self.length_m + 0.5:
                raise ValueError(f"{d.variant_id}: stop beyond the end of the route")
        return self

    def direction(self, direction: Direction) -> RouteDirection:
        return next(d for d in self.directions if d.direction is direction)

    def variant(self, variant_id: str) -> RouteDirection:
        for d in self.directions:
            if d.variant_id == variant_id:
                return d
        raise KeyError(f"route {self.id} has no variant {variant_id}")

    def polyline(self, direction: Direction = Direction.TO_CAMPUS) -> Polyline:
        """Geometry in the direction of travel (cached)."""
        if direction not in self._polylines:
            fwd = Polyline(
                coords=tuple((c[0], c[1]) for c in self.path.coordinates),
                cum=tuple(self.cum_dist_m),
            )
            self._polylines[Direction.TO_CAMPUS] = fwd
            self._polylines[Direction.FROM_CAMPUS] = fwd.reversed()
        return self._polylines[direction]

    def segment_class_at(self, distance_m: float, direction: Direction = Direction.TO_CAMPUS) -> SegmentClass:
        """Road class at a distance along the route in the given direction's frame."""
        d_fwd = distance_m if direction is Direction.TO_CAMPUS else self.length_m - distance_m
        seg = self.polyline(Direction.TO_CAMPUS).interpolate(d_fwd).segment_index
        return self.segment_classes[seg]

    def serves(self, stop_id: str) -> list[Direction]:
        return [d.direction for d in self.directions if d.stop(stop_id) is not None]
