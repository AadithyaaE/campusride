"""DTOs for route deviation (``/buses/{id}/route-status``, ``/alerts``) — Feature 10."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.models import Alert, LineString
from app.models.common import RouteStatus, Severity
from app.services.route_anomaly_service import BusRouteStatus


class LatLonOut(BaseModel):
    lat: float
    lon: float


class RouteThresholdsOut(BaseModel):
    minor_m: float
    major_m: float


class RouteStatusOut(BaseModel):
    """The route remains the planned route; demo deviation changes the synthetic bus position."""

    bus_id: str
    trip_id: str | None
    route_id: str | None
    route_direction_id: str | None
    route_status: RouteStatus
    deviation_distance_m: float | None
    """Shortest distance (m) from the tracked position to the planned route geometry."""
    thresholds: RouteThresholdsOut
    expected_route: LineString | None
    """Planned geometry of the current trip, in the direction of travel (null: no active trip)."""
    current_location: LatLonOut | None
    """The TRACKED position (the same point the maps show)."""
    nearest_route_point: LatLonOut | None
    """Closest point of the planned route (null when within the corridor fast path)."""
    timestamp: datetime | None
    """Time of the fix the status is based on."""
    evaluated_at: datetime
    source: Literal["synthetic", "device"]
    major_alert_active: bool
    message: str | None
    """Observed condition only, e.g. "BUS B05 is 312 m off its planned route." """

    @classmethod
    def of(cls, r: BusRouteStatus, *, minor_m: float, major_m: float) -> RouteStatusOut:
        s, chk = r.state, r.check
        running = chk.status not in (
            RouteStatus.NO_ACTIVE_TRIP,
            RouteStatus.NO_LIVE_DATA,
            RouteStatus.NO_ROUTE,
        )
        expected = None
        if running and r.route is not None and s is not None and s.direction is not None:
            line = r.route.polyline(s.direction)
            expected = LineString(type="LineString", coordinates=[(c[0], c[1]) for c in line.coords])
        message = None
        if chk.distance_m is not None and chk.status in (
            RouteStatus.MINOR_DEVIATION,
            RouteStatus.MAJOR_DEVIATION,
        ):
            message = f"BUS {r.bus_id} is {round(chk.distance_m)} m off its planned route."
        return cls(
            bus_id=r.bus_id,
            trip_id=s.trip_id if s else None,
            route_id=s.route_id if s else None,
            route_direction_id=s.variant_id if s else None,
            route_status=chk.status,
            deviation_distance_m=chk.distance_m,
            thresholds=RouteThresholdsOut(minor_m=minor_m, major_m=major_m),
            expected_route=expected,
            current_location=(
                LatLonOut(lat=s.location.coordinates[1], lon=s.location.coordinates[0]) if s else None
            ),
            nearest_route_point=(
                LatLonOut(lat=chk.nearest_route_point[1], lon=chk.nearest_route_point[0])
                if chk.nearest_route_point
                else None
            ),
            timestamp=s.ts if s else None,
            evaluated_at=r.evaluated_at,
            source=r.source,
            major_alert_active=r.open_deviation is not None,
            message=message,
        )


class AlertOut(BaseModel):
    id: str
    type: str
    severity: Severity
    title: str
    body: str
    payload: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None
    active: bool

    @classmethod
    def of(cls, a: Alert) -> AlertOut:
        return cls(
            id=a.id,
            type=a.type.value,
            severity=a.severity,
            title=a.title,
            body=a.body,
            payload=a.payload,
            created_at=a.created_at,
            resolved_at=a.resolved_at,
            active=a.resolved_at is None,
        )
