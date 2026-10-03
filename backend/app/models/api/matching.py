"""DTOs for stop ↔ bus matching (``/stops/{id}/buses``, ``/students/me/stop/buses``)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.core.clock import Clock
from app.models import GeoPoint, Stop
from app.models.common import BusStatus, Direction, RouteStatus, StopProximity
from app.models.route import RouteStop
from app.services.capacity import available_seats, occupancy_percentage_display
from app.services.matching import ServingBus
from app.services.route_anomaly_service import live_route_status
from app.services.tracking import is_delayed


class StopRefOut(BaseModel):
    id: str
    name: str
    seq: int
    """Position in the bus's current route direction (0-based)."""


class BusPositionOut(BaseModel):
    """Authoritative position of the bus among its route direction's ordered stops."""

    current_stop: StopRefOut
    """The stop the bus is at, else the last stop it reached."""
    previous_stop: StopRefOut | None
    next_stop: StopRefOut | None
    at_stop: bool
    distance_to_next_stop_m: float | None


class StopMatchOut(BaseModel):
    """The bus relative to the requested stop."""

    stop_id: str
    proximity: StopProximity
    position: Literal["behind", "current", "ahead"]
    distance_to_stop_m: float | None
    """Along-route distance still to travel; null once the stop has been passed."""
    stop_offset_m: float
    stops_away: int | None
    progress_to_stop: float
    dwelling_at_stop: bool


class StopBusOut(BaseModel):
    bus_id: str
    bus_number: str
    reg_no: str
    capacity: int
    route_id: str
    route_direction_id: str
    route_name: str
    direction: Direction
    direction_label: str
    status: BusStatus
    schedule_status: Literal["on_time", "delayed"]
    delay_s: int
    location: GeoPoint
    speed_mps: float
    heading_deg: float | None
    route_progress: float
    occupancy: int
    available_seats: int
    occupancy_percentage: int | None
    """Backend-computed (``services/capacity.py``); null when capacity is unknown."""
    last_updated: datetime
    stale: bool
    route_status: RouteStatus | None
    """Feature 10 route status of this bus (backend-evaluated)."""
    deviation_distance_m: float | None
    position: BusPositionOut
    match: StopMatchOut | None
    """Null only for a student's assigned bus that is not currently serving their stop."""
    is_assigned_bus: bool = False

    @classmethod
    def of(
        cls,
        sb: ServingBus,
        stops: dict[str, Stop],
        clock: Clock,
        stale_after_s: float,
        *,
        assigned_bus_id: str | None = None,
    ) -> StopBusOut:
        s, p, m = sb.state, sb.position, sb.match

        def ref(rs: RouteStop | None) -> StopRefOut | None:
            if rs is None:
                return None
            stop = stops.get(rs.stop_id)
            return StopRefOut(id=rs.stop_id, name=stop.name if stop else rs.stop_id, seq=rs.seq)

        current = ref(p.current)
        assert current is not None
        return cls(
            bus_id=sb.bus.id,
            bus_number=sb.bus.id,
            reg_no=sb.bus.reg_no,
            capacity=sb.bus.capacity,
            route_id=sb.route.id,
            route_direction_id=p.direction.variant_id,
            route_name=sb.route.name,
            direction=p.direction.direction,
            direction_label=p.direction.label,
            status=s.status,
            schedule_status="delayed" if is_delayed(s) else "on_time",
            delay_s=s.delay_s,
            location=s.location,
            speed_mps=s.speed_mps,
            heading_deg=s.heading_deg,
            route_progress=s.route_progress,
            occupancy=s.occupancy,
            available_seats=available_seats(s.occupancy, sb.bus.capacity),
            occupancy_percentage=occupancy_percentage_display(s.occupancy, sb.bus.capacity),
            last_updated=s.ts,
            stale=(clock.now() - s.last_seen).total_seconds() > stale_after_s,
            route_status=live_route_status(s, now=clock.now(), stale_after_s=stale_after_s),
            deviation_distance_m=s.deviation_m,
            position=BusPositionOut(
                current_stop=current,
                previous_stop=ref(p.previous),
                next_stop=ref(p.next),
                at_stop=p.at_stop is not None,
                distance_to_next_stop_m=p.distance_to_next_m,
            ),
            match=None
            if m is None
            else StopMatchOut(
                stop_id=m.stop.stop_id,
                proximity=m.proximity,
                position=m.position,
                distance_to_stop_m=m.distance_to_stop_m,
                stop_offset_m=m.stop_offset_m,
                stops_away=m.stops_away,
                progress_to_stop=m.progress_to_stop,
                dwelling_at_stop=m.dwelling_at_stop,
            ),
            is_assigned_bus=sb.bus.id == assigned_bus_id,
        )


class StopSummaryOut(BaseModel):
    id: str
    name: str


class StopBusesOut(BaseModel):
    stop: StopSummaryOut
    buses: list[StopBusOut]
    """Buses whose CURRENT route direction serves the stop, nearest-relevant first."""


class MyStopBusesOut(BaseModel):
    student_id: str
    status: Literal["assigned", "unassigned"]
    boarding_stop: StopSummaryOut | None
    assigned_bus_id: str | None
    route_direction_id: str | None
    direction: Direction | None
    my_bus: StopBusOut | None
    """The college-assigned bus (null if unassigned or it has not reported yet)."""
    my_bus_serving_stop: bool
    """True when the assigned bus is currently operating the assigned direction through the stop."""
    other_buses: list[StopBusOut]
    """Other buses serving the boarding stop in the assigned direction — information only."""
