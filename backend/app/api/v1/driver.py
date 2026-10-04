"""Driver endpoints. Telemetry from a real driver phone enters here; the
simulator calls the SAME ``TelemetryIngestService.ingest`` in-process.

Feature 12 (Driver App): everything is derived from the signed-in driver — no bus,
route or trip id is ever accepted from the client. Feature 12 uses synthetic GPS;
actual device GPS is not implemented yet.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from app.api.v1.buses import BusLiveOut
from app.core.auth import Principal
from app.deps import Container, require_role
from app.models import LineString
from app.models.api.driver import (
    DriverDashboardOut,
    DriverRouteOut,
    DriverRouteViewOut,
    DriverStopOut,
)
from app.models.api.route_status import LatLonOut
from app.models.common import Role, TripStatus
from app.models.telemetry_in import TelemetryBatchIn
from app.services.driver_service import DriverService

router = APIRouter(tags=["driver"])

StopState = Literal["passed", "current", "next", "upcoming"]

Driver = Annotated[Principal, Depends(require_role(Role.DRIVER))]


def _svc(c: Container) -> DriverService:
    return DriverService(c.repos, c.settings, c.clock, c.simulator)


@router.post("/driver/telemetry", response_model=BusLiveOut, status_code=202)
async def post_telemetry(batch: TelemetryBatchIn, principal: Driver, c: Container) -> BusLiveOut:
    """Ingest GPS fixes for the driver's own bus; returns the derived bus state."""
    state = await c.telemetry_ingest().ingest(batch, principal)
    bus = await c.repos.buses.get(state.id)
    return BusLiveOut.of(state, c.clock, c.settings.bus_stale_after_s, bus.capacity if bus else None)


@router.get("/driver/me", response_model=DriverDashboardOut)
async def driver_me(principal: Driver, c: Container) -> DriverDashboardOut:
    """The driver's profile, assigned bus/route, current or next trip and live bus state."""
    return DriverDashboardOut.of(await _svc(c).context(principal))


@router.post("/driver/trip/start", response_model=DriverDashboardOut)
async def start_trip(principal: Driver, c: Container) -> DriverDashboardOut:
    """Start the driver's OWN next trip; the existing simulator then emits synthetic GPS."""
    return DriverDashboardOut.of(await _svc(c).start_trip(principal))


@router.post("/driver/trip/stop", response_model=DriverDashboardOut)
async def stop_trip(principal: Driver, c: Container) -> DriverDashboardOut:
    """Finalize the driver's active trip where the bus is; its telemetry then stops."""
    return DriverDashboardOut.of(await _svc(c).stop_trip(principal))


@router.post("/driver/simulate-gps", response_model=DriverDashboardOut)
async def simulate_gps(principal: Driver, c: Container) -> DriverDashboardOut:
    """Demo control: one synthetic GPS fix for the driver's bus right now (same pipeline)."""
    return DriverDashboardOut.of(await _svc(c).simulate_gps(principal))


@router.get("/driver/route", response_model=DriverRouteViewOut)
async def driver_route(principal: Driver, c: Container) -> DriverRouteViewOut:
    """Ordered stops of the current/next trip with progress from the tracked state."""
    ctx = await _svc(c).context(principal)
    if ctx.route is None or ctx.trip is None:
        return DriverRouteViewOut(route=None, trip_id=None, stops=[], bus_location=None, path=None)
    d = ctx.route.variant(ctx.trip.variant_id)
    s = ctx.state if ctx.state is not None and ctx.state.trip_id == ctx.trip.id else None
    seq_of = {rs.stop_id: rs.seq for rs in d.stops}
    cur = seq_of.get(s.current_stop_id) if s and s.current_stop_id else None
    nxt = seq_of.get(s.next_stop_id) if s and s.next_stop_id else None
    done = ctx.trip.status is TripStatus.COMPLETED

    def state_of(seq: int) -> StopState:
        if done or (cur is not None and seq < cur):
            return "passed"
        if cur is not None and seq == cur:
            return "current"
        if nxt is not None and seq == nxt:
            return "next"
        return "upcoming"

    line = ctx.route.polyline(d.direction)
    return DriverRouteViewOut(
        route=DriverRouteOut(
            id=ctx.route.id,
            name=ctx.route.name,
            color=ctx.route.color,
            route_direction_id=d.variant_id,
            direction=d.direction,
            label=d.label,
        ),
        trip_id=ctx.trip.id,
        stops=[
            DriverStopOut(
                seq=rs.seq,
                stop_id=rs.stop_id,
                name=ctx.stops[rs.stop_id].name if rs.stop_id in ctx.stops else rs.stop_id,
                state=state_of(rs.seq),
            )
            for rs in d.stops
        ],
        bus_location=(
            LatLonOut(lat=ctx.state.location.coordinates[1], lon=ctx.state.location.coordinates[0])
            if ctx.state is not None
            else None
        ),
        path=LineString(type="LineString", coordinates=[(p[0], p[1]) for p in line.coords]),
    )
