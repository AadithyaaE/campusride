"""Stop ↔ route-direction ↔ bus matching (authoritative, backend).

Inputs are ONLY:
* the bus's tracked ``BusState`` (current trip's route direction + distance
  along it, derived from telemetry by tracking), and
* the route direction's ORDERED stop list with each stop's distance along that
  direction (Phase 1 reference data).

Nothing here scans route geometry or compares latitude/longitude, so it is
cheap per request and two buses that are geographically close but on
different routes / directions are never confused.

Rules (radius = ``STOP_ARRIVAL_RADIUS_M``, approach = ``STOP_APPROACHING_M``):

* A bus SERVES a stop  ⇔  its current trip's route direction (``variant_id``,
  e.g. ``R2`` vs ``R2-E``) contains the stop.
* Relative to a stop at along-route offset Δ = stop_d − bus_d:
    COMPLETED trip            → AT_STOP if it is the final stop, else PASSED_STOP
    |Δ| ≤ radius              → AT_STOP          (position "current")
    Δ < −radius               → PASSED_STOP      (position "behind")
    radius < Δ ≤ approach     → APPROACHING_STOP (position "ahead")
    Δ > approach              → FAR_FROM_STOP    (position "ahead")
* current stop = the stop the bus is at, else the last stop it reached;
  previous = the stop before that in sequence; next = first stop beyond radius.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.models import Bus, BusState, Route, Stop
from app.models.common import BusStatus, Direction, StopProximity
from app.models.route import RouteDirection, RouteStop
from app.repositories import Repositories
from app.services.assignments import AssignmentService, ResolvedAssignment

StopPosition = Literal["behind", "current", "ahead"]

STOPPED_STATUSES = (BusStatus.DWELLING, BusStatus.AT_DEPOT, BusStatus.COMPLETED)
_PROXIMITY_ORDER = {
    StopProximity.AT_STOP: 0,
    StopProximity.APPROACHING_STOP: 1,
    StopProximity.FAR_FROM_STOP: 2,
    StopProximity.PASSED_STOP: 3,
}


# =========================================================================== pure functions


@dataclass(frozen=True)
class StopsAround:
    near: RouteStop | None
    """Nearest stop within ``radius`` of the bus (it may be passing or dwelling)."""
    last_reached: RouteStop
    """Last stop at or behind the bus (the first stop before departure)."""
    next: RouteStop | None
    """First stop strictly beyond ``radius`` ahead of the bus."""


def stops_around(direction: RouteDirection, distance_m: float, radius_m: float) -> StopsAround:
    """Where a distance falls in a direction's ORDERED stop sequence (shared with tracking)."""
    stops = direction.stops
    near = None
    best = radius_m
    for s in stops:
        gap = abs(s.distance_along_m - distance_m)
        if gap <= best:
            near, best = s, gap
    reached = [s for s in stops if s.distance_along_m <= distance_m + radius_m]
    nxt = next((s for s in stops if s.distance_along_m > distance_m + radius_m), None)
    return StopsAround(near=near, last_reached=reached[-1] if reached else stops[0], next=nxt)


@dataclass(frozen=True)
class BusPosition:
    """A bus located on its current route direction."""

    direction: RouteDirection
    distance_m: float
    at_stop: RouteStop | None
    current: RouteStop
    previous: RouteStop | None
    next: RouteStop | None
    distance_to_next_m: float | None


def locate(state: BusState, direction: RouteDirection, radius_m: float) -> BusPosition:
    d = state.distance_along_m
    around = stops_around(direction, d, radius_m)
    stops = direction.stops
    if state.status is BusStatus.COMPLETED:
        at_stop: RouteStop | None = stops[-1]
        current, nxt = stops[-1], None
    else:
        at_stop = around.near if state.status in STOPPED_STATUSES else None
        current = at_stop or around.last_reached
        nxt = around.next
    previous = stops[current.seq - 1] if current.seq > 0 else None
    return BusPosition(
        direction=direction,
        distance_m=d,
        at_stop=at_stop,
        current=current,
        previous=previous,
        next=nxt,
        distance_to_next_m=round(max(0.0, nxt.distance_along_m - d), 1) if nxt else None,
    )


@dataclass(frozen=True)
class StopMatch:
    """A bus relative to one stop it serves."""

    stop: RouteStop
    proximity: StopProximity
    position: StopPosition
    distance_to_stop_m: float | None
    """Along-route distance still to travel (0 at the stop, None once passed)."""
    stop_offset_m: float
    """Signed along-route offset: stop − bus (positive = ahead)."""
    stops_away: int | None
    """0 at the stop, 1 if it is the next stop, …; None once passed."""
    progress_to_stop: float
    """Share of the way from the route direction's start to this stop (0..1)."""
    dwelling_at_stop: bool


def match_stop(
    state: BusState,
    direction: RouteDirection,
    stop_id: str,
    *,
    radius_m: float,
    approaching_m: float,
) -> StopMatch | None:
    """None ⇔ the bus's current route direction does not contain the stop."""
    rs = direction.stop(stop_id)
    if rs is None:
        return None
    d = state.distance_along_m
    offset = rs.distance_along_m - d
    final = direction.stops[-1]

    if state.status is BusStatus.COMPLETED:
        proximity = StopProximity.AT_STOP if rs.seq == final.seq else StopProximity.PASSED_STOP
    elif abs(offset) <= radius_m:
        proximity = StopProximity.AT_STOP
    elif offset < 0:
        proximity = StopProximity.PASSED_STOP
    elif offset <= approaching_m:
        proximity = StopProximity.APPROACHING_STOP
    else:
        proximity = StopProximity.FAR_FROM_STOP

    position: StopPosition = (
        "current"
        if proximity is StopProximity.AT_STOP
        else "behind"
        if proximity is StopProximity.PASSED_STOP
        else "ahead"
    )
    if proximity is StopProximity.AT_STOP:
        stops_away: int | None = 0
    elif proximity is StopProximity.PASSED_STOP:
        stops_away = None
    else:
        stops_away = sum(
            1 for s in direction.stops if d + radius_m < s.distance_along_m <= rs.distance_along_m
        )

    passed = proximity is StopProximity.PASSED_STOP
    return StopMatch(
        stop=rs,
        proximity=proximity,
        position=position,
        distance_to_stop_m=None if passed else round(max(0.0, offset), 1),
        stop_offset_m=round(offset, 1),
        stops_away=stops_away,
        progress_to_stop=1.0
        if rs.distance_along_m <= 0
        else round(min(1.0, max(0.0, d / rs.distance_along_m)), 4),
        dwelling_at_stop=proximity is StopProximity.AT_STOP and state.status in STOPPED_STATUSES,
    )


# =========================================================================== service


@dataclass(frozen=True)
class ServingBus:
    """One bus with its position on its current route direction and (optionally) a stop match."""

    bus: Bus
    state: BusState
    route: Route
    position: BusPosition
    match: StopMatch | None


@dataclass(frozen=True)
class StudentStopBuses:
    assignment: ResolvedAssignment
    my_bus: ServingBus | None
    """The assigned bus. ``match`` is None when it is not currently serving the stop
    in the assigned direction (e.g. between trips)."""
    others: list[ServingBus]
    """Other buses currently serving the boarding stop in the assignment's direction."""


def _sort_key(sb: ServingBus) -> tuple:
    m = sb.match
    if m is None:
        return (9, 0.0, sb.bus.id)
    return (_PROXIMITY_ORDER[m.proximity], m.distance_to_stop_m or 0.0, sb.bus.id)


class MatchingService:
    """Deterministic matching over indexed reference data + current bus state.

    Routes are static reference data and cached per service instance (one per
    app container); bus states are read fresh on every call.
    """

    def __init__(self, repos: Repositories, settings: Settings) -> None:
        self._repos = repos
        self._radius = settings.stop_arrival_radius_m
        self._approach = settings.stop_approaching_m
        self._routes: dict[str, Route] = {}

    async def _route(self, route_id: str) -> Route | None:
        if route_id not in self._routes:
            route = await self._repos.routes.get(route_id)
            if route is None:
                return None
            self._routes[route_id] = route
        return self._routes[route_id]

    def forget_routes(self) -> None:
        self._routes.clear()

    async def stop_names(self, serving: list[ServingBus]) -> dict[str, Stop]:
        """Stops referenced by these buses' current/previous/next stops (one query)."""
        ids = {
            rs.stop_id
            for sb in serving
            for rs in (sb.position.current, sb.position.previous, sb.position.next)
            if rs is not None
        }
        return {s.id: s for s in await self._repos.stops.get_many(list(ids))}

    async def position_of(self, bus: Bus, state: BusState, stop_id: str | None = None) -> ServingBus | None:
        """Locate a bus on its current route direction (+ match ``stop_id`` if given)."""
        if state.variant_id is None or state.route_id is None:
            return None
        route = await self._route(state.route_id)
        if route is None:
            return None
        try:
            direction = route.variant(state.variant_id)
        except KeyError:
            return None
        match = (
            match_stop(state, direction, stop_id, radius_m=self._radius, approaching_m=self._approach)
            if stop_id
            else None
        )
        return ServingBus(
            bus=bus, state=state, route=route, position=locate(state, direction, self._radius), match=match
        )

    async def buses_serving_stop(
        self, stop_id: str, *, direction: Direction | None = None
    ) -> list[ServingBus]:
        """Buses whose CURRENT route direction contains ``stop_id`` (optionally one direction only)."""
        if await self._repos.stops.get(stop_id) is None:
            raise NotFoundError(f"stop {stop_id} not found")
        routes = await self._repos.routes.serving_stop(stop_id)  # indexed: directions.stops.stop_id
        for r in routes:
            self._routes.setdefault(r.id, r)
        variant_ids = [
            d.variant_id
            for r in routes
            for d in r.directions
            if d.stop(stop_id) is not None and (direction is None or d.direction is direction)
        ]
        if not variant_ids:
            return []
        states = await self._repos.bus_states.by_variants(variant_ids)
        buses = {b.id: b for b in await self._repos.buses.get_many([s.id for s in states])}
        out: list[ServingBus] = []
        for s in states:
            bus = buses.get(s.id)
            sb = await self.position_of(bus, s, stop_id) if bus else None
            if sb is not None and sb.match is not None:
                out.append(sb)
        return sorted(out, key=_sort_key)

    async def bus_serves_stop(self, bus_id: str, stop_id: str) -> ServingBus | None:
        """The bus's match for ``stop_id``, or None if its current direction doesn't serve it."""
        bus = await self._repos.buses.get(bus_id)
        if bus is None:
            raise NotFoundError(f"bus {bus_id} not found")
        state = await self._repos.bus_states.get(bus_id)
        if state is None:
            return None
        sb = await self.position_of(bus, state, stop_id)
        return sb if sb is not None and sb.match is not None else None

    async def for_student(self, student_id: str) -> StudentStopBuses | None:
        """The student's assigned bus + other buses at their boarding stop. None if unassigned."""
        resolved = await AssignmentService(self._repos).for_student(student_id)
        if resolved is None:
            return None
        stop_id = resolved.boarding_stop.id
        serving = await self.buses_serving_stop(stop_id, direction=resolved.direction.direction)
        mine = next((sb for sb in serving if sb.bus.id == resolved.bus.id), None)
        if mine is None:  # assigned bus not currently serving the stop in this direction
            state = await self._repos.bus_states.get(resolved.bus.id)
            mine = await self.position_of(resolved.bus, state) if state else None
        others = [sb for sb in serving if sb.bus.id != resolved.bus.id]
        return StudentStopBuses(assignment=resolved, my_bus=mine, others=others)
