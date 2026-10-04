"""DTOs for the Driver App (Feature 12). Synthetic GPS only — no device GPS yet."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models import LineString
from app.models.api.route_status import LatLonOut
from app.models.common import BusStatus, Direction, RouteStatus, TripStatus
from app.services.capacity import available_seats, occupancy_percentage_display
from app.services.driver_service import DriverContext
from app.services.tracking import is_delayed


class DriverInfoOut(BaseModel):
    id: str
    name: str
    phone: str


class DriverBusOut(BaseModel):
    id: str
    number: str
    reg_no: str
    capacity: int


class DriverRouteOut(BaseModel):
    id: str
    name: str
    color: str
    route_direction_id: str | None
    direction: Direction | None
    label: str | None


class DriverTripOut(BaseModel):
    id: str
    status: TripStatus
    scheduled_start: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    first_stop: str | None
    last_stop: str | None


class DriverLiveOut(BaseModel):
    """The bus's tracked state — the SAME ``BusState`` students and admins see."""

    location: LatLonOut
    speed_kmh: int
    heading_deg: float | None
    bus_status: BusStatus
    current_stop: str | None
    next_stop: str | None
    occupancy: int
    capacity: int
    available_seats: int
    occupancy_percentage: int | None
    delay_minutes: int
    schedule_status: Literal["on_time", "delayed"]
    route_status: RouteStatus | None
    deviation_distance_m: float | None
    last_fix_at: datetime


class DriverDashboardOut(BaseModel):
    driver: DriverInfoOut
    bus: DriverBusOut | None
    route: DriverRouteOut | None
    trip: DriverTripOut | None
    trip_state: Literal["READY", "ACTIVE", "COMPLETED", "NO_TRIP", "NO_ASSIGNMENT"]
    control: Literal["driver", "schedule"]
    """``driver``: Start/Stop Trip control this bus. ``schedule``: it runs on the demo schedule."""
    can_start: bool
    can_stop: bool
    next_stop: str | None
    """Next stop while driving; the first stop of the trip before it starts."""
    gps: Literal["LIVE", "STALE", "UNAVAILABLE"]
    """From backend telemetry freshness (``BUS_STALE_AFTER_S``)."""
    gps_source: Literal["simulated"] = "simulated"
    live: DriverLiveOut | None
    message: str | None

    @classmethod
    def of(cls, c: DriverContext) -> DriverDashboardOut:
        def name(stop_id: str | None) -> str | None:
            return None if stop_id is None else (c.stops[stop_id].name if stop_id in c.stops else stop_id)

        d = c.route.variant(c.trip.variant_id) if c.route and c.trip else None
        s = c.state
        live = None
        if s is not None and c.bus is not None:
            live = DriverLiveOut(
                location=LatLonOut(lat=s.location.coordinates[1], lon=s.location.coordinates[0]),
                speed_kmh=round(s.speed_mps * 3.6),
                heading_deg=s.heading_deg,
                bus_status=s.status,
                current_stop=name(s.current_stop_id),
                next_stop=name(s.next_stop_id),
                occupancy=s.occupancy,
                capacity=c.bus.capacity,
                available_seats=available_seats(s.occupancy, c.bus.capacity),
                occupancy_percentage=occupancy_percentage_display(s.occupancy, c.bus.capacity),
                delay_minutes=round(s.delay_s / 60),
                schedule_status="delayed" if is_delayed(s) else "on_time",
                route_status=s.route_status,
                deviation_distance_m=s.deviation_m,
                last_fix_at=s.ts,
            )
        on_trip = s is not None and c.trip is not None and s.trip_id == c.trip.id
        if c.trip_state == "ACTIVE" and on_trip and s is not None:
            next_stop = name(s.next_stop_id)
        elif c.trip_state == "READY" and d is not None:
            next_stop = name(d.stops[0].stop_id)
        else:
            next_stop = None
        message = {
            "NO_ASSIGNMENT": "You have no bus assigned. Please contact the transport office.",
            "NO_TRIP": "No trips are scheduled for your bus today.",
            "COMPLETED": "All of today's trips are completed.",
        }.get(c.trip_state)
        if message is None and c.control == "schedule":
            message = "This bus runs on the automatic demo schedule; trips start and stop by themselves."
        return cls(
            driver=DriverInfoOut(id=c.driver.id, name=c.driver.name, phone=c.driver.phone),
            bus=(
                DriverBusOut(id=c.bus.id, number=c.bus.id, reg_no=c.bus.reg_no, capacity=c.bus.capacity)
                if c.bus
                else None
            ),
            route=(
                DriverRouteOut(
                    id=c.route.id,
                    name=c.route.name,
                    color=c.route.color,
                    route_direction_id=d.variant_id if d else None,
                    direction=d.direction if d else None,
                    label=d.label if d else None,
                )
                if c.route
                else None
            ),
            trip=(
                DriverTripOut(
                    id=c.trip.id,
                    status=c.trip.status,
                    scheduled_start=c.trip.scheduled_start,
                    actual_start=c.trip.actual_start,
                    actual_end=c.trip.actual_end,
                    first_stop=name(d.stops[0].stop_id) if d else None,
                    last_stop=name(d.stops[-1].stop_id) if d else None,
                )
                if c.trip
                else None
            ),
            trip_state=c.trip_state,
            control=c.control,
            can_start=c.control == "driver" and c.trip_state == "READY",
            can_stop=c.control == "driver" and c.trip_state == "ACTIVE",
            next_stop=next_stop,
            gps=c.gps,
            live=live,
            message=message,
        )


class DriverStopOut(BaseModel):
    seq: int
    stop_id: str
    name: str
    state: Literal["passed", "current", "next", "upcoming"]


class DriverRouteViewOut(BaseModel):
    route: DriverRouteOut | None
    trip_id: str | None
    stops: list[DriverStopOut]
    """Ordered stops of the current/next trip, with progress from the tracked state."""
    bus_location: LatLonOut | None
    path: LineString | None
    """Planned geometry (the same authored route the web maps draw)."""
