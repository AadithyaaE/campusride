"""Route deviation detection (Feature 10): how far is a bus from its PLANNED route?

The route remains the planned route; demo deviation changes the synthetic bus
position, not the route geometry.

Input is the TRACKED position (``BusState.location`` — the same point the maps
show), the authored road geometry of the bus's current route direction
(``Route.polyline(direction)``, never the stops) and the clock.

  distance  = shortest geographic distance (m) from the point to the planned
              LineString (``geo.project_point`` over the WHOLE line: every segment,
              local metric frame, so lat/lng is never treated as metres)
  status    = NORMAL           distance ≤ ROUTE_MINOR_DEVIATION_M      (50 m)
              MINOR_DEVIATION  minor < distance < ROUTE_MAJOR_DEVIATION_M (150 m)
              MAJOR_DEVIATION  distance ≥ major
  no answer = NO_LIVE_DATA (no state) · NO_ACTIVE_TRIP (between trips / completed)
              · NO_ROUTE (geometry missing) · STALE (fix older than BUS_STALE_AFTER_S)
              · INVALID_LOCATION (non-finite / out-of-range coordinates)

Evaluation happens in the telemetry pipeline (``TelemetryIngestService``), so
alerts follow STATE TRANSITIONS, never API polling:
  → MAJOR (from anything else)  open a ``Deviation`` + one ROUTE_DEVIATION alert (AlertService)
  MAJOR → MAJOR                 nothing new (max distance tracked on the deviation)
  MAJOR → anything else         deviation RESOLVED, alert ``resolved_at`` set
A MAJOR deviation also marks the bus ``BusStatus.DEVIATED`` (the existing status
Features 7/9 already treat as "off route"); MINOR is informational only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.clock import Clock
from app.core.config import Settings
from app.core.events import EventBus
from app.geo import LngLat, project_point
from app.models import BusState, Deviation, Route
from app.models.common import BusStatus, DeviationStatus, RouteStatus
from app.models.events import DeviationEnded, DeviationStarted
from app.repositories import Repositories
from app.services.alert_service import AlertService
from app.services.tracking import is_stale

DEVIATION_STATES = (RouteStatus.NORMAL, RouteStatus.MINOR_DEVIATION, RouteStatus.MAJOR_DEVIATION)


# =========================================================================== pure geometry / rules


def valid_point(p: LngLat) -> bool:
    lng, lat = p
    return math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and -90 <= lat <= 90


def distance_to_route_m(
    coords: tuple[LngLat, ...], cum: tuple[float, ...], p: LngLat
) -> tuple[float, LngLat]:
    """Shortest distance (m) from ``p`` to the polyline and the nearest point on it."""
    proj = project_point(coords, cum, p)
    return proj.offset_m, proj.snapped


def classify(distance_m: float, *, minor_m: float, major_m: float) -> RouteStatus:
    if distance_m >= major_m:
        return RouteStatus.MAJOR_DEVIATION
    if distance_m > minor_m:
        return RouteStatus.MINOR_DEVIATION
    return RouteStatus.NORMAL


AlertAction = Literal["raise", "resolve"]


def alert_action(prev: RouteStatus | None, new: RouteStatus) -> AlertAction | None:
    """Alerts follow transitions: entering MAJOR raises, leaving MAJOR resolves."""
    was_major = prev is RouteStatus.MAJOR_DEVIATION
    is_major = new is RouteStatus.MAJOR_DEVIATION
    if is_major and not was_major:
        return "raise"
    if was_major and not is_major:
        return "resolve"
    return None


@dataclass(frozen=True)
class RouteCheck:
    status: RouteStatus
    distance_m: float | None
    nearest_route_point: LngLat | None


def evaluate(
    state: BusState | None,
    route: Route | None,
    *,
    now: datetime,
    stale_after_s: float,
    minor_m: float,
    major_m: float,
    corridor_offset_m: float | None = None,
) -> RouteCheck:
    """Route status of one bus right now (pure).

    ``corridor_offset_m`` (optional fast path): tracking's offset from the route near the
    bus's own progress. It can never be smaller than the true shortest distance, so when
    it is within the minor threshold the bus is certainly NORMAL and the whole-line scan
    is skipped (the reported distance is then that offset). The API always scans.
    """
    if state is None:
        return RouteCheck(RouteStatus.NO_LIVE_DATA, None, None)
    if state.trip_id is None or state.direction is None or state.status is BusStatus.COMPLETED:
        return RouteCheck(RouteStatus.NO_ACTIVE_TRIP, None, None)
    if route is None or len(route.path.coordinates) < 2:
        return RouteCheck(RouteStatus.NO_ROUTE, None, None)
    if is_stale(state, now, stale_after_s):
        return RouteCheck(RouteStatus.STALE, None, None)
    p = state.location.lnglat
    if not valid_point(p):
        return RouteCheck(RouteStatus.INVALID_LOCATION, None, None)
    if corridor_offset_m is not None and corridor_offset_m <= minor_m:
        return RouteCheck(RouteStatus.NORMAL, round(corridor_offset_m, 1), None)
    line = route.polyline(state.direction)
    d, nearest = distance_to_route_m(line.coords, line.cum, p)
    return RouteCheck(classify(d, minor_m=minor_m, major_m=major_m), round(d, 1), nearest)


def alert_message(bus_id: str, distance_m: float) -> str:
    """Observed condition only — never a cause."""
    return f"BUS {bus_id} is {round(distance_m)} m off its planned route."


# =========================================================================== service


class RouteAnomalyService:
    """Evaluates tracked states and keeps deviations/alerts in step with transitions."""

    def __init__(
        self,
        repos: Repositories,
        events: EventBus,
        settings: Settings,
        clock: Clock,
        alerts: AlertService | None = None,
    ) -> None:
        self._repos = repos
        self._events = events
        self._settings = settings
        self._clock = clock
        self._alerts = alerts or AlertService(repos, events, clock, settings)
        """Feature 11: deviation alerts are created/resolved by the central alert service."""

    def check(
        self,
        state: BusState | None,
        route: Route | None,
        *,
        now: datetime | None = None,
        corridor_offset_m: float | None = None,
    ) -> RouteCheck:
        s = self._settings
        return evaluate(
            state,
            route,
            now=now or self._clock.now(),
            stale_after_s=s.bus_stale_after_s,
            minor_m=s.route_minor_deviation_m,
            major_m=s.route_major_deviation_m,
            corridor_offset_m=corridor_offset_m,
        )

    async def apply(
        self, prev: BusState | None, state: BusState, route: Route | None, *, source: str = "synthetic"
    ) -> BusState:
        """Called by the ingest service for every new fix (state is fresh → never STALE here)."""
        chk = self.check(state, route, now=state.ts, corridor_offset_m=state.off_route_m)
        update: dict = {"route_status": chk.status, "deviation_m": chk.distance_m}
        if chk.status is RouteStatus.MAJOR_DEVIATION and state.status in (
            BusStatus.EN_ROUTE,
            BusStatus.DWELLING,
        ):
            update["status"] = BusStatus.DEVIATED
        new_state = state.model_copy(update=update)

        prev_status = prev.route_status if prev is not None else None
        if prev is not None and prev.trip_id != state.trip_id:
            if prev_status is RouteStatus.MAJOR_DEVIATION:  # a new trip closes the old deviation
                await self._resolve(new_state, prev)
            prev_status = None
        action = alert_action(prev_status, chk.status)
        if action == "raise":
            await self._raise(new_state, chk, source)
        elif action == "resolve":
            await self._resolve(new_state, prev)
        elif chk.status is RouteStatus.MAJOR_DEVIATION:
            await self._track_max(new_state, chk)
        return new_state

    async def _raise(self, state: BusState, chk: RouteCheck, source: str) -> None:
        assert state.trip_id is not None and chk.distance_m is not None
        dev = Deviation(
            id=f"DEV-{state.trip_id}-{state.id}-{int(state.ts.timestamp())}",
            trip_id=state.trip_id,
            bus_id=state.id,
            started_at=state.ts,
            max_off_route_m=chk.distance_m,
        )
        await self._repos.deviations.upsert(dev)
        await self._alerts.raise_route_deviation(state, chk.distance_m, dev.id, source)
        await self._events.publish(
            DeviationStarted(
                ts=state.ts,
                deviation_id=dev.id,
                bus_id=state.id,
                trip_id=state.trip_id,
                off_route_m=chk.distance_m,
            )
        )

    async def _track_max(self, state: BusState, chk: RouteCheck) -> None:
        dev = await self._repos.deviations.open_for_bus(state.id)
        if dev is not None and chk.distance_m is not None and chk.distance_m > dev.max_off_route_m:
            await self._repos.deviations.upsert(dev.model_copy(update={"max_off_route_m": chk.distance_m}))

    async def _resolve(self, state: BusState, prev: BusState | None) -> None:
        dev = await self._repos.deviations.open_for_bus(state.id)
        if dev is None:
            return
        await self._repos.deviations.upsert(
            dev.model_copy(update={"status": DeviationStatus.RESOLVED, "ended_at": state.ts})
        )
        await self._alerts.resolve_route_deviation(state.id, state.ts)
        await self._events.publish(
            DeviationEnded(
                ts=state.ts,
                deviation_id=dev.id,
                bus_id=state.id,
                trip_id=dev.trip_id,
                max_off_route_m=dev.max_off_route_m,
            )
        )


# =========================================================================== reads (API)


@dataclass(frozen=True)
class BusRouteStatus:
    bus_id: str
    state: BusState | None
    route: Route | None
    check: RouteCheck
    evaluated_at: datetime
    source: Literal["synthetic", "device"]
    open_deviation: Deviation | None


def live_route_status(state: BusState, *, now: datetime, stale_after_s: float) -> RouteStatus | None:
    """What a live view should show from the STORED evaluation (STALE once fixes stop)."""
    if is_stale(state, now, stale_after_s):
        return RouteStatus.STALE
    return state.route_status


async def bus_route_status(service: RouteAnomalyService, bus_id: str) -> BusRouteStatus | None:
    """Fresh, exact evaluation for one bus (whole-line distance); None if the bus is unknown."""
    repos = service._repos
    bus = await repos.buses.get(bus_id)
    if bus is None:
        return None
    state = await repos.bus_states.get(bus_id)
    route = await repos.routes.get(state.route_id) if state is not None and state.route_id else None
    now = service._clock.now()
    return BusRouteStatus(
        bus_id=bus_id,
        state=state,
        route=route,
        check=service.check(state, route, now=now),
        evaluated_at=now,
        source="synthetic" if bus.source.value == "sim" else "device",
        open_deviation=await repos.deviations.open_for_bus(bus_id),
    )
