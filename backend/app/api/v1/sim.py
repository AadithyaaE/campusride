"""DEVELOPMENT / DEMO simulator controls.

Allowed for any signed-in user only when APP_ENV is ``dev`` or ``test``;
otherwise admins only. They control the SYNTHETIC simulation clock and never
touch student assignments. (APP_ENV=prod with mock auth is rejected at startup.)
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import Principal
from app.core.clock import ALLOWED_SIM_SPEEDS
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ServiceUnavailableError
from app.deps import Container, CurrentPrincipal
from app.models.common import Role
from app.services.bus_simulator import BusSimulator, SimulatorStatus

router = APIRouter(tags=["simulator (dev/demo)"])


class SimStatusOut(BaseModel):
    enabled: bool
    running: bool
    paused: bool
    speed: float
    allowed_speeds: list[int]
    sim_time: datetime | None
    local_time: datetime | None
    start_time: datetime | None
    service_date: str | None
    buses: int
    telemetry_interval_s: float | None
    controls_allowed: bool
    """Whether the CALLER may use start/pause/reset/speed."""
    route_deviation: dict[str, Literal["normal", "minor", "major"]]
    """Demo route deviation in force: ``{"*": mode}`` = all buses, else per bus id. Empty = normal."""


class RouteDeviationIn(BaseModel):
    """Demo control (Feature 10): shift SYNTHETIC GPS off the planned route."""

    mode: Literal["normal", "minor", "major"]
    bus_id: str | None = None
    """One simulated bus, or every simulated bus when omitted."""


class SpeedIn(BaseModel):
    speed: int


def _controls_allowed(principal: Principal, c) -> bool:
    return c.settings.app_env in ("dev", "test") or principal.role is Role.ADMIN


def _out(st: SimulatorStatus | None, allowed: bool) -> SimStatusOut:
    if st is None:
        return SimStatusOut(
            enabled=False,
            running=False,
            paused=True,
            speed=0,
            allowed_speeds=list(ALLOWED_SIM_SPEEDS),
            sim_time=None,
            local_time=None,
            start_time=None,
            service_date=None,
            buses=0,
            telemetry_interval_s=None,
            controls_allowed=False,
            route_deviation={},
        )
    return SimStatusOut(
        enabled=True,
        running=st.running,
        paused=st.paused,
        speed=st.speed,
        allowed_speeds=list(st.allowed_speeds),
        sim_time=st.sim_time,
        local_time=st.local_time,
        start_time=st.start_time,
        service_date=st.service_date,
        buses=st.buses,
        telemetry_interval_s=st.telemetry_interval_s,
        controls_allowed=allowed,
        route_deviation=dict(st.route_deviation or {}),
    )


async def controlled_simulator(principal: CurrentPrincipal, c: Container) -> tuple[BusSimulator, bool]:
    if c.simulator is None:
        raise ServiceUnavailableError("the synthetic simulator is disabled (SIM_ENABLED / CLOCK_MODE)")
    allowed = _controls_allowed(principal, c)
    if not allowed:
        raise ForbiddenError("simulator controls are admin-only outside development")
    return c.simulator, allowed


Controlled = Annotated[tuple[BusSimulator, bool], Depends(controlled_simulator)]


@router.get("/sim/status", response_model=SimStatusOut)
async def sim_status(principal: CurrentPrincipal, c: Container) -> SimStatusOut:
    return _out(c.simulator.status() if c.simulator else None, _controls_allowed(principal, c))


@router.post("/sim/start", response_model=SimStatusOut)
async def sim_start(ctl: Controlled) -> SimStatusOut:
    sim, allowed = ctl
    return _out(await sim.start(), allowed)


@router.post("/sim/pause", response_model=SimStatusOut)
async def sim_pause(ctl: Controlled) -> SimStatusOut:
    sim, allowed = ctl
    return _out(await sim.pause(), allowed)


@router.post("/sim/reset", response_model=SimStatusOut)
async def sim_reset(ctl: Controlled) -> SimStatusOut:
    """Back to the start time (e.g. 07:15): trips reset, buses at their first stops."""
    sim, allowed = ctl
    return _out(await sim.reset(), allowed)


@router.put("/sim/speed", response_model=SimStatusOut)
async def sim_speed(body: SpeedIn, ctl: Controlled) -> SimStatusOut:
    sim, allowed = ctl
    if body.speed not in ALLOWED_SIM_SPEEDS:
        raise ConflictError(f"speed must be one of {list(ALLOWED_SIM_SPEEDS)}")
    return _out(sim.set_speed(body.speed), allowed)


@router.post("/sim/route-deviation", response_model=SimStatusOut)
async def sim_route_deviation(body: RouteDeviationIn, ctl: Controlled) -> SimStatusOut:
    """Demo: ``normal`` / ``minor`` / ``major`` deviation for one simulated bus or all of them.

    Changes only the synthetic GPS the simulator emits (the planned route is untouched);
    the backend then classifies the tracked position. Reset returns every bus to normal.
    """
    sim, allowed = ctl
    try:
        return _out(sim.set_route_deviation(body.mode, body.bus_id), allowed)
    except KeyError as exc:
        raise NotFoundError(f"bus {body.bus_id} is not a simulated bus with trips today") from exc
