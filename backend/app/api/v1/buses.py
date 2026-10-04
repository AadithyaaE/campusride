"""Fleet reference data + current live state (derived from telemetry by tracking).

``live`` is null until the bus has reported telemetry. For simulated buses it
is SYNTHETIC (``source: "sim"``) — never present it as real GPS.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.clock import Clock
from app.core.errors import NotFoundError
from app.deps import Container, CurrentPrincipal
from app.models import Bus, BusState, GeoPoint
from app.models.api.boarding import OccupancyOut
from app.models.api.eta import BusEtaOut, EtaPredictionOut
from app.models.api.route_status import RouteStatusOut
from app.models.common import BusSource, BusStatus, Direction, FleetStatus, RouteStatus
from app.services.capacity import available_seats, occupancy_percentage_display
from app.services.route_anomaly_service import bus_route_status, live_route_status
from app.services.tracking import is_delayed

router = APIRouter(tags=["buses"])


class BusLiveOut(BaseModel):
    trip_id: str | None
    route_id: str | None
    route_direction_id: str | None
    direction: Direction | None
    location: GeoPoint
    speed_mps: float
    heading_deg: float | None
    status: BusStatus
    schedule_status: Literal["on_time", "delayed"]
    delay_s: int
    current_stop_id: str | None
    next_stop_id: str | None
    route_progress: float
    distance_along_m: float
    occupancy: int
    available_seats: int | None
    """``max(capacity − occupancy, 0)`` — null when the capacity isn't known here."""
    occupancy_percentage: int | None
    boarded_count: int
    """QR boardings on the current trip (included in ``occupancy``)."""
    route_status: RouteStatus | None
    """Feature 10: NORMAL / MINOR_DEVIATION / MAJOR_DEVIATION (or STALE…), from the backend."""
    deviation_distance_m: float | None
    last_updated: datetime
    stale: bool

    @classmethod
    def of(cls, s: BusState, clock: Clock, stale_after_s: float, capacity: int | None = None) -> BusLiveOut:
        return cls(
            trip_id=s.trip_id,
            route_id=s.route_id,
            route_direction_id=s.variant_id,
            direction=s.direction,
            location=s.location,
            speed_mps=s.speed_mps,
            heading_deg=s.heading_deg,
            status=s.status,
            schedule_status="delayed" if is_delayed(s) else "on_time",
            delay_s=s.delay_s,
            current_stop_id=s.current_stop_id,
            next_stop_id=s.next_stop_id,
            route_progress=s.route_progress,
            distance_along_m=s.distance_along_m,
            occupancy=s.occupancy,
            available_seats=None if capacity is None else available_seats(s.occupancy, capacity),
            occupancy_percentage=(
                None if capacity is None else occupancy_percentage_display(s.occupancy, capacity)
            ),
            boarded_count=s.boarded_count,
            route_status=live_route_status(s, now=clock.now(), stale_after_s=stale_after_s),
            deviation_distance_m=s.deviation_m,
            last_updated=s.ts,
            stale=(clock.now() - s.last_seen).total_seconds() > stale_after_s,
        )


class BusOut(BaseModel):
    id: str
    reg_no: str
    capacity: int
    route_id: str
    """Physical route the bus runs (both directions)."""
    status: FleetStatus
    source: BusSource
    """``sim`` = synthetic simulator bus, ``device`` = real driver phone."""
    live: BusLiveOut | None
    """Current state from telemetry, or null if the bus hasn't reported yet."""


class StopRefOut(BaseModel):
    id: str
    name: str


class BusDetailOut(BusOut):
    current_stop: StopRefOut | None
    next_stop: StopRefOut | None
    simulation_paused: bool | None
    """Whether the synthetic simulation clock is paused (null when no simulator)."""


def _bus_out(b: Bus, state: BusState | None, c) -> dict:
    return {
        "id": b.id,
        "reg_no": b.reg_no,
        "capacity": b.capacity,
        "route_id": b.default_route_id,
        "status": b.status,
        "source": b.source,
        "live": (BusLiveOut.of(state, c.clock, c.settings.bus_stale_after_s, b.capacity) if state else None),
    }


def bus_out(b: Bus, state: BusState | None, c) -> BusOut:
    """The ``GET /buses`` item for one bus (also pushed over the WebSocket, Feature 14)."""
    return BusOut(**_bus_out(b, state, c))


@router.get("/buses", response_model=list[BusOut])
async def list_buses(_: CurrentPrincipal, c: Container) -> list[BusOut]:
    """The fleet with each bus's current (synthetic or device) live state."""
    states = {s.id: s for s in await c.repos.bus_states.list()}
    return [bus_out(b, states.get(b.id), c) for b in await c.repos.buses.list()]


@router.get("/buses/{bus_id}", response_model=BusDetailOut)
async def get_bus(bus_id: str, _: CurrentPrincipal, c: Container) -> BusDetailOut:
    bus = await c.repos.buses.get(bus_id)
    if bus is None:
        raise NotFoundError(f"bus {bus_id} not found")
    state = await c.repos.bus_states.get(bus_id)
    ids = [i for i in (state.current_stop_id if state else None, state.next_stop_id if state else None) if i]
    stops = {s.id: s for s in await c.repos.stops.get_many(ids)} if ids else {}

    def ref(stop_id: str | None) -> StopRefOut | None:
        s = stops.get(stop_id or "")
        return StopRefOut(id=s.id, name=s.name) if s else None

    return BusDetailOut(
        **_bus_out(bus, state, c),
        current_stop=ref(state.current_stop_id if state else None),
        next_stop=ref(state.next_stop_id if state else None),
        simulation_paused=c.simulator.status().paused if c.simulator else None,
    )


@router.get("/buses/{bus_id}/eta", response_model=BusEtaOut)
async def bus_eta(
    bus_id: str,
    _: CurrentPrincipal,
    c: Container,
    stop_id: str = Query(description="Target stop; must be on the bus's CURRENT route direction"),
) -> BusEtaOut:
    """Backend ETA of ``bus_id`` at ``stop_id``.

    404 unknown bus/stop · 409 the bus has no live state, or its current route
    direction does not serve the stop · 200 with ``status`` passed/completed/at_stop.
    """
    sb, pred = await c.eta().bus_eta(bus_id, stop_id)
    m = sb.match
    assert m is not None
    stop = await c.repos.stops.get(stop_id)
    return BusEtaOut(
        **EtaPredictionOut.of(pred).model_dump(),
        bus_id=sb.bus.id,
        bus_number=sb.bus.id,
        reg_no=sb.bus.reg_no,
        stop_id=stop_id,
        stop_name=stop.name if stop else stop_id,
        route_id=sb.route.id,
        route_direction_id=sb.position.direction.variant_id,
        direction=sb.position.direction.direction,
        proximity=m.proximity,
        distance_to_stop_m=m.distance_to_stop_m,
        stops_away=m.stops_away,
        delay_s=sb.state.delay_s,
    )


@router.get("/buses/{bus_id}/occupancy", response_model=OccupancyOut)
async def bus_occupancy(bus_id: str, _: CurrentPrincipal, c: Container) -> OccupancyOut:
    """Live occupancy = min(capacity, synthetic baseline + QR boardings on the current trip)."""
    return OccupancyOut.of(await c.boarding().occupancy(bus_id))


@router.get("/buses/{bus_id}/route-status", response_model=RouteStatusOut)
async def route_status(bus_id: str, _: CurrentPrincipal, c: Container) -> RouteStatusOut:
    """Distance from the TRACKED position to the PLANNED route geometry, and its status.

    The route remains the planned route; demo deviation changes the synthetic bus position.
    """
    r = await bus_route_status(c.route_anomaly(), bus_id)
    if r is None:
        raise NotFoundError(f"bus {bus_id} not found")
    s = c.settings
    return RouteStatusOut.of(r, minor_m=s.route_minor_deviation_m, major_m=s.route_major_deviation_m)
