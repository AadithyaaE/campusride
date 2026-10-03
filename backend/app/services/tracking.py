"""Telemetry ingestion and tracking: telemetry → BusState.

``TelemetryIngestService.ingest`` is THE ingestion path. It is called by
``POST /api/v1/driver/telemetry`` (a driver's phone) and, in-process, by the
synthetic bus simulator acting as a driver. Nothing downstream can tell the
two apart except ``Telemetry.meta.source``.

Tracking derives everything from the reported fixes alone (position, speed,
time) — it never reads simulator internals:

* projection onto the trip's route direction (windowed, so a route that
  revisits a road cannot snap to the wrong pass) → distance, progress, off-route
* current / next stop, DWELLING when stopped within STOP_ARRIVAL_RADIUS_M
* trip ACTIVE on first departure, COMPLETED at the final stop
* schedule delay vs. the timetable interpolated at the current position
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.core.auth import Principal
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import ForbiddenError, NotFoundError
from app.core.events import EventBus
from app.models import Bus, BusState, GeoPoint, Route, Telemetry, TelemetryMeta, Trip
from app.models.common import BusSource, BusStatus, Role, TripStatus
from app.models.events import (
    BusStateUpdated,
    StopArrived,
    StopDeparted,
    TelemetryReceived,
    TripEnded,
    TripStarted,
)
from app.models.route import RouteDirection
from app.models.telemetry_in import TelemetryBatchIn, TelemetryPointIn
from app.repositories import Repositories
from app.services.capacity import live_occupancy
from app.services.matching import stops_around

MOVING_MPS = 0.5
"""Below this reported speed the bus counts as stopped."""
DELAYED_AFTER_S = 300
"""Schedule delay (5 min) at which a bus is shown as DELAYED."""
MAX_PLAUSIBLE_SPEED_MPS = 30.0
"""Upper bound used to size the projection window after a gap between fixes."""


def scheduled_offset_at(direction: RouteDirection, d: float) -> float:
    """Timetable seconds-after-departure at distance ``d`` (linear between stops)."""
    stops = direction.stops
    if d <= stops[0].distance_along_m:
        return float(stops[0].scheduled_offset_s)
    for a, b in zip(stops, stops[1:]):
        if d <= b.distance_along_m:
            span = b.distance_along_m - a.distance_along_m
            frac = 0.0 if span <= 0 else (d - a.distance_along_m) / span
            return a.scheduled_offset_s + frac * (b.scheduled_offset_s - a.scheduled_offset_s)
    return float(stops[-1].scheduled_offset_s)


def is_stale(state: BusState, now: datetime, stale_after_s: float) -> bool:
    """No fix for longer than ``BUS_STALE_AFTER_S`` — position/timing can't be trusted."""
    return (now - state.last_seen).total_seconds() > stale_after_s


def is_delayed(state: BusState) -> bool:
    return state.delay_s >= DELAYED_AFTER_S and state.status in (BusStatus.EN_ROUTE, BusStatus.DWELLING)


class TrackingService:
    """Pure-ish state derivation; persistence and events are done by the ingest service."""

    def __init__(self, settings: Settings) -> None:
        self._radius = settings.stop_arrival_radius_m

    def derive(
        self,
        prev: BusState | None,
        bus: Bus,
        trip: Trip | None,
        route: Route | None,
        point: TelemetryPointIn,
    ) -> BusState:
        loc = GeoPoint.of(point.lng, point.lat)
        speed = point.speed_mps or 0.0
        baseline = (
            point.occupancy if point.occupancy is not None else (prev.occupancy_baseline if prev else 0)
        )
        same = prev is not None and trip is not None and prev.trip_id == trip.id
        boarded = prev.boarded_count if same and prev else 0  # re-counted by the ingest service
        base = {
            "id": bus.id,
            "ts": point.ts,
            "last_seen": point.ts,
            "location": loc,
            "speed_mps": speed,
            "heading_deg": point.heading_deg,
            "occupancy": live_occupancy(
                baseline=baseline, boarded=0, capacity=bus.capacity, trip_completed=False
            ),
            "occupancy_baseline": baseline,
            "boarded_count": boarded,
            "stale": False,
        }
        if trip is None or route is None:
            return BusState(**base, status=BusStatus.SCHEDULED)

        direction = route.variant(trip.variant_id)
        line = route.polyline(direction.direction)
        same_trip = prev is not None and prev.trip_id == trip.id
        hint = prev.distance_along_m if same_trip and prev else 0.0
        gap_s = max(0.0, (point.ts - prev.ts).total_seconds()) if same_trip and prev else 0.0
        ahead = max(3_000.0, MAX_PLAUSIBLE_SPEED_MPS * gap_s + 200.0)
        proj = line.project_near(loc.lnglat, hint, back_m=200.0, ahead_m=ahead)
        d = proj.distance_along_m
        stops = direction.stops
        stopped = speed < MOVING_MPS

        around = stops_around(direction, d, self._radius)  # shared with matching
        at_stop = around.near if stopped else None

        final = stops[-1]
        if trip.status is TripStatus.COMPLETED or (
            at_stop is not None and at_stop.seq == final.seq and trip.status is TripStatus.ACTIVE
        ):
            status = BusStatus.COMPLETED
        elif trip.status is TripStatus.SCHEDULED and (
            stopped or d <= stops[0].distance_along_m + self._radius
        ):
            status = BusStatus.AT_DEPOT
        elif at_stop is not None:
            status = BusStatus.DWELLING
        else:
            status = BusStatus.EN_ROUTE

        current = at_stop or around.last_reached
        nxt = around.next
        if status is BusStatus.COMPLETED:
            current, nxt = final, None

        delay = 0
        if status in (BusStatus.EN_ROUTE, BusStatus.DWELLING, BusStatus.COMPLETED):
            elapsed = (point.ts - trip.scheduled_start).total_seconds()
            delay = round(elapsed - scheduled_offset_at(direction, d))
            if status is BusStatus.COMPLETED and prev is not None and same_trip:
                delay = prev.delay_s if prev.status is BusStatus.COMPLETED else delay

        departures = dict(prev.last_stop_departures) if same_trip and prev else {}
        if (
            same_trip
            and prev is not None
            and prev.current_stop_id
            and prev.status in (BusStatus.DWELLING, BusStatus.AT_DEPOT)
            and status is BusStatus.EN_ROUTE
        ):
            departures[prev.current_stop_id] = point.ts

        base["occupancy"] = live_occupancy(
            baseline=baseline,
            boarded=boarded,
            capacity=bus.capacity,
            trip_completed=status is BusStatus.COMPLETED,
        )
        return BusState(
            **base,
            trip_id=trip.id,
            route_id=route.id,
            variant_id=direction.variant_id,
            direction=direction.direction,
            distance_along_m=round(d, 2),
            off_route_m=round(proj.offset_m, 2),
            route_progress=round(min(1.0, max(0.0, d / route.length_m)), 4),
            next_stop_seq=nxt.seq if nxt else None,
            current_stop_id=current.stop_id,
            next_stop_id=nxt.stop_id if nxt else None,
            delay_s=delay,
            status=status,
            last_stop_departures=departures,
        )


class TelemetryIngestService:
    """Authorise → persist telemetry → derive BusState → publish events."""

    def __init__(self, repos: Repositories, events: EventBus, clock: Clock, settings: Settings) -> None:
        self._repos = repos
        self._events = events
        self._clock = clock
        self._tracking = TrackingService(settings)
        self._routes: dict[str, Route] = {}
        self._buses: dict[str, Bus] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        from app.services.route_anomaly_service import RouteAnomalyService  # avoids an import cycle

        self.anomaly = RouteAnomalyService(repos, events, settings, clock)
        """Feature 10 — evaluated on every fix, so deviation alerts follow state, not polling."""

    def _lock_for(self, bus_id: str) -> asyncio.Lock:
        """Serialises BusState read-modify-write per bus (telemetry vs. QR boarding)."""
        return self._locks.setdefault(bus_id, asyncio.Lock())

    async def _with_boardings(self, state: BusState, bus: Bus) -> BusState:
        """Apply the occupancy rule with the AUTHORITATIVE boarding count for the trip."""
        boarded = await self._repos.boarding_events.count_for_trip(state.trip_id) if state.trip_id else 0
        occupancy = live_occupancy(
            baseline=state.occupancy_baseline,
            boarded=boarded,
            capacity=bus.capacity,
            trip_completed=state.status is BusStatus.COMPLETED,
        )
        return state.model_copy(update={"boarded_count": boarded, "occupancy": occupancy})

    async def refresh_occupancy(self, bus_id: str) -> BusState | None:
        """Re-derive occupancy right after a boarding (no new telemetry needed)."""
        bus = await self._bus(bus_id)
        async with self._lock_for(bus_id):
            state = await self._repos.bus_states.get(bus_id)
            if state is None:
                return None
            state = await self._with_boardings(state, bus)
            await self._repos.bus_states.upsert(state)
        await self._events.publish(BusStateUpdated(ts=state.ts, state=state))
        return state

    async def _bus(self, bus_id: str) -> Bus:
        if bus_id not in self._buses:
            bus = await self._repos.buses.get(bus_id)
            if bus is None:
                raise NotFoundError(f"bus {bus_id} not found")
            self._buses[bus_id] = bus
        return self._buses[bus_id]

    async def _route(self, route_id: str) -> Route:
        if route_id not in self._routes:
            route = await self._repos.routes.get(route_id)
            if route is None:
                raise NotFoundError(f"route {route_id} not found")
            self._routes[route_id] = route
        return self._routes[route_id]

    async def _authorize(self, principal: Principal, bus: Bus) -> None:
        if principal.role is not Role.DRIVER:
            raise ForbiddenError("only drivers (or the simulator acting as one) may send telemetry")
        if principal.source == "sim":
            if principal.bus_id != bus.id:
                raise ForbiddenError(f"simulator principal is bound to {principal.bus_id}, not {bus.id}")
            return
        driver = await self._repos.drivers.by_user(principal.user_id)
        if driver is None or bus.driver_id != driver.id:
            raise ForbiddenError(f"you are not the assigned driver of bus {bus.id}")

    async def ingest(self, batch: TelemetryBatchIn, principal: Principal) -> BusState:
        bus = await self._bus(batch.bus_id)
        await self._authorize(principal, bus)

        trip: Trip | None = None
        route: Route | None = None
        if batch.trip_id is not None:
            trip = await self._repos.trips.get(batch.trip_id)
            if trip is None:
                raise NotFoundError(f"trip {batch.trip_id} not found")
            if trip.bus_id != bus.id:
                raise ForbiddenError(f"trip {trip.id} belongs to bus {trip.bus_id}, not {bus.id}")
            route = await self._route(trip.route_id)

        source = BusSource.SIM if principal.source == "sim" else BusSource.DEVICE
        points = sorted(batch.points, key=lambda p: p.ts)
        await self._repos.telemetry.append_many(
            [
                Telemetry(
                    ts=p.ts,
                    meta=TelemetryMeta(bus_id=bus.id, trip_id=batch.trip_id, source=source),
                    location=GeoPoint.of(p.lng, p.lat),
                    speed_mps=p.speed_mps,
                    heading_deg=p.heading_deg,
                    accuracy_m=p.accuracy_m,
                )
                for p in points
            ]
        )
        await self._events.publish(
            TelemetryReceived(ts=points[-1].ts, bus_id=bus.id, trip_id=batch.trip_id, count=len(points))
        )

        async with self._lock_for(bus.id):
            state = await self._repos.bus_states.get(bus.id)
            before = state
            for p in points:
                prev = state
                state = self._tracking.derive(prev, bus, trip, route, p)
                if trip is not None:
                    trip = await self._update_trip(trip, prev, state, p.ts)
                    await self._stop_events(prev, state, p.ts)
            assert state is not None
            state = await self._with_boardings(state, bus)  # simulator ticks never erase boardings
            state = await self.anomaly.apply(
                before, state, route, source="synthetic" if source is BusSource.SIM else "device"
            )
            await self._repos.bus_states.upsert(state)
        await self._events.publish(BusStateUpdated(ts=state.ts, state=state))
        return state

    async def _update_trip(self, trip: Trip, prev: BusState | None, state: BusState, at: datetime) -> Trip:
        if trip.status is TripStatus.SCHEDULED and state.status in (BusStatus.EN_ROUTE, BusStatus.DWELLING):
            trip = await self._repos.trips.set_status(trip.id, TripStatus.ACTIVE, at) or trip
            await self._events.publish(
                TripStarted(
                    ts=at,
                    trip_id=trip.id,
                    bus_id=trip.bus_id,
                    route_id=trip.route_id,
                    variant_id=trip.variant_id,
                    direction=trip.direction,
                )
            )
        elif trip.status is TripStatus.ACTIVE and state.status is BusStatus.COMPLETED:
            trip = await self._repos.trips.set_status(trip.id, TripStatus.COMPLETED, at) or trip
            await self._events.publish(
                TripEnded(ts=at, trip_id=trip.id, bus_id=trip.bus_id, variant_id=trip.variant_id)
            )
        return trip

    async def _stop_events(self, prev: BusState | None, state: BusState, at: datetime) -> None:
        if state.trip_id is None or state.variant_id is None:
            return
        was_at = (
            prev.current_stop_id
            if prev and prev.trip_id == state.trip_id and prev.status is BusStatus.DWELLING
            else None
        )
        now_at = state.current_stop_id if state.status is BusStatus.DWELLING else None
        common = {"ts": at, "bus_id": state.id, "trip_id": state.trip_id, "variant_id": state.variant_id}
        if now_at and now_at != was_at:
            seq = (state.next_stop_seq or 1) - 1
            await self._events.publish(StopArrived(**common, stop_id=now_at, seq=seq))
        if was_at and now_at != was_at:
            seq = (prev.next_stop_seq or 1) - 1 if prev else 0
            await self._events.publish(StopDeparted(**common, stop_id=was_at, seq=seq))

    def forget_caches(self) -> None:
        self._routes.clear()
        self._buses.clear()
