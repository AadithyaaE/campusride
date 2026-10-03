"""DTOs for stops and routes."""

from __future__ import annotations

from pydantic import BaseModel

from app.models import GeoPoint, LineString, Route, Stop
from app.models.common import Direction
from app.models.route import RouteDirection, RouteStop
from app.services.reference import ServiceAtStop


class StopOut(BaseModel):
    id: str
    name: str
    location: GeoPoint
    walk_radius_m: float
    is_campus_terminal: bool

    @classmethod
    def of(cls, s: Stop) -> StopOut:
        return cls(
            id=s.id,
            name=s.name,
            location=s.location,
            walk_radius_m=s.walk_radius_m,
            is_campus_terminal=s.is_campus_terminal,
        )


class NearbyStopOut(StopOut):
    distance_m: float


class StopServiceOut(BaseModel):
    """One route direction serving a stop."""

    route_id: str
    variant_id: str
    direction: Direction
    label: str
    color: str
    seq: int
    distance_along_m: float
    scheduled_offset_s: int

    @classmethod
    def of(cls, s: ServiceAtStop) -> StopServiceOut:
        return cls(
            route_id=s.route.id,
            variant_id=s.direction.variant_id,
            direction=s.direction.direction,
            label=s.direction.label,
            color=s.route.color,
            seq=s.route_stop.seq,
            distance_along_m=s.route_stop.distance_along_m,
            scheduled_offset_s=s.route_stop.scheduled_offset_s,
        )


class DirectionSummaryOut(BaseModel):
    variant_id: str
    direction: Direction
    label: str
    stop_count: int
    first_stop_id: str
    last_stop_id: str


class RouteSummaryOut(BaseModel):
    id: str
    name: str
    color: str
    length_m: float
    directions: list[DirectionSummaryOut]

    @classmethod
    def of(cls, r: Route) -> RouteSummaryOut:
        return cls(
            id=r.id,
            name=r.name,
            color=r.color,
            length_m=round(r.length_m, 1),
            directions=[
                DirectionSummaryOut(
                    variant_id=d.variant_id,
                    direction=d.direction,
                    label=d.label,
                    stop_count=len(d.stops),
                    first_stop_id=d.stops[0].stop_id,
                    last_stop_id=d.stops[-1].stop_id,
                )
                for d in r.directions
            ],
        )


class RouteStopOut(BaseModel):
    stop_id: str
    name: str
    location: GeoPoint
    seq: int
    distance_along_m: float
    scheduled_offset_s: int
    dwell_s: int

    @classmethod
    def of(cls, rs: RouteStop, stop: Stop) -> RouteStopOut:
        return cls(
            stop_id=rs.stop_id,
            name=stop.name,
            location=stop.location,
            seq=rs.seq,
            distance_along_m=rs.distance_along_m,
            scheduled_offset_s=rs.scheduled_offset_s,
            dwell_s=rs.dwell_s,
        )


class RouteDirectionOut(BaseModel):
    variant_id: str
    direction: Direction
    label: str
    stops: list[RouteStopOut]

    @classmethod
    def of(cls, d: RouteDirection, stops: dict[str, Stop]) -> RouteDirectionOut:
        return cls(
            variant_id=d.variant_id,
            direction=d.direction,
            label=d.label,
            stops=[RouteStopOut.of(rs, stops[rs.stop_id]) for rs in d.stops],
        )


class RouteDetailOut(BaseModel):
    id: str
    name: str
    color: str
    length_m: float
    path: LineString
    """TO_CAMPUS orientation; FROM_CAMPUS travels it in reverse."""
    directions: list[RouteDirectionOut]

    @classmethod
    def of(cls, r: Route, stops: dict[str, Stop]) -> RouteDetailOut:
        return cls(
            id=r.id,
            name=r.name,
            color=r.color,
            length_m=round(r.length_m, 1),
            path=r.path,
            directions=[RouteDirectionOut.of(d, stops) for d in r.directions],
        )
