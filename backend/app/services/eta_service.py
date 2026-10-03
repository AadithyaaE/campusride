"""Backend ETA prediction (deterministic, no ML) + multi-bus arrivals.

Inputs (all existing backend data — no simulator internals, no external APIs):

* Feature 4 matching (``ServingBus``): which stop, along-route distance to it,
  stops in between, current/next stop, proximity. No second matching algorithm.
* Tracked ``BusState``: current speed, status (moving / dwelling / at depot),
  schedule delay, staleness.
* ``TrafficProfile`` per road class (free-flow speed × time-of-day factor) —
  the same synthetic assumptions the simulator uses — and each route
  direction's per-segment road classes.
* The route direction's timetable (``scheduled_offset_s``) as the prototype's
  "historical average" travel time. These are planned, not observed, times;
  they are labelled ``history_source = "timetable"`` and never presented as
  real observations.

Formula (seconds), for a bus that has not yet reached the stop:

    D            = matching.distance_to_stop_m                    (along the route)
    model_time   = Σ_class D_class / (free_flow_class × traffic_factor_class(time of day))
    v_model      = D / model_time
    v_eff        = clamp(w·current_speed + (1−w)·v_model, 2.5, 22 m/s)
                   w = 0.5 (≤1.5 km) / 0.25 (further) if the bus is moving, else 0
                   → no division by zero when dwelling / stopped
    travel       = D / v_eff
    dwell        = Σ dwell_s of intermediate stops (+ half the current stop's dwell if dwelling there)
    timetable    = scheduled_offset(stop) − scheduled_offset(bus position)      (includes dwell)
    delay_factor = clamp(1 + delay_s / max(scheduled_elapsed, 600 s), 0.8, 1.5)
    combined     = 0.65·(travel + dwell) + 0.35·(timetable × delay_factor)     (model only, if no timetable)
    wait         = time until scheduled departure, if the bus hasn't left its first stop
    ETA          = wait + combined

Delay is NOT added as minutes: the bus's current position already contains
all past lateness. ``delay_factor`` only rescales the timetable pace for the
remaining distance (a bus running slower than planned so far is expected to
keep that pace), so lateness is never counted twice.

Confidence (prototype input-quality score, NOT statistically calibrated):
+1 moving or dwelling (speed is meaningful) · +1 timetable available ·
+1 traffic profiles for every road class · +1 within 2 km or ≤ 2 stops ·
−2 stale fix · −1 bus has not departed yet.  ≥ 3 high · 2 medium · ≤ 1 low.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.models import BusState, Route, TrafficProfile
from app.models.common import BusStatus, Direction, SegmentClass, StopProximity
from app.models.route import RouteDirection
from app.repositories import Repositories
from app.services.assignments import ResolvedAssignment
from app.services.matching import MatchingService, ServingBus
from app.services.tracking import scheduled_offset_at

EtaStatus = Literal["predicted", "at_stop", "passed", "completed"]
Confidence = Literal["high", "medium", "low"]
TrafficLevel = Literal["Low", "Moderate", "High"]

MOVING_MPS = 1.5
MIN_EFFECTIVE_MPS = 2.5
MAX_EFFECTIVE_MPS = 22.0
NEAR_CURRENT_SPEED_WEIGHT = 0.5
FAR_CURRENT_SPEED_WEIGHT = 0.25
NEAR_BLEND_M = 1_500.0
MODEL_WEIGHT = 0.65
TIMETABLE_WEIGHT = 0.35
DELAY_FACTOR_RANGE = (0.8, 1.5)
MIN_ELAPSED_FOR_PACE_S = 600.0
CURRENT_DWELL_SHARE = 0.5
NEAR_STOP_M = 2_000.0
LOW_TRAFFIC_MAX = 1.15
MODERATE_TRAFFIC_MAX = 1.5

_STATUS_ORDER = {"at_stop": 0, "predicted": 1, "completed": 2, "passed": 3}


@dataclass(frozen=True)
class EtaPrediction:
    status: EtaStatus
    computed_at: datetime
    eta_s: float | None
    confidence: Confidence
    traffic_level: TrafficLevel
    traffic_factor: float
    """Remaining-route travel time ÷ free-flow time (1.0 = empty roads; higher = slower)."""
    delay_factor: float
    travel_s: float = 0.0
    dwell_s: float = 0.0
    wait_s: float = 0.0
    timetable_s: float | None = None
    history_source: Literal["timetable"] | None = None

    @property
    def estimated_arrival(self) -> datetime | None:
        return None if self.eta_s is None else self.computed_at + timedelta(seconds=self.eta_s)

    @property
    def eta_minutes(self) -> int | None:
        """User-facing whole minutes: 0 means "<1 min" (or at the stop)."""
        if self.eta_s is None:
            return None
        return 0 if self.eta_s < 60 else math.ceil(self.eta_s / 60)


# =========================================================================== road-class distances


class DirectionClassTable:
    """Cumulative distance per road class along ONE route direction (built once, cached).

    Lets the service split any [d0, d1] span by road class in O(log n) instead
    of rescanning geometry per request.
    """

    def __init__(self, route: Route, direction: RouteDirection) -> None:
        line = route.polyline(direction.direction)
        n_seg = len(line.coords) - 1
        self.cum = line.cum
        self.seg_class: list[SegmentClass] = [
            route.segment_classes[j if direction.direction is Direction.TO_CAMPUS else n_seg - 1 - j]
            for j in range(n_seg)
        ]
        running = {c: 0.0 for c in SegmentClass}
        self.by_class: dict[SegmentClass, list[float]] = {c: [0.0] for c in SegmentClass}
        for j in range(n_seg):
            running[self.seg_class[j]] += self.cum[j + 1] - self.cum[j]
            for c in SegmentClass:
                self.by_class[c].append(running[c])

    def _at(self, d: float) -> dict[SegmentClass, float]:
        d = min(max(d, 0.0), self.cum[-1])
        i = min(max(bisect.bisect_right(self.cum, d) - 1, 0), len(self.seg_class) - 1)
        out = {c: self.by_class[c][i] for c in SegmentClass}
        out[self.seg_class[i]] += d - self.cum[i]
        return out

    def between(self, d0: float, d1: float) -> dict[SegmentClass, float]:
        a, b = self._at(d0), self._at(d1)
        return {c: max(0.0, b[c] - a[c]) for c in SegmentClass}


# =========================================================================== pure prediction


def traffic_level(factor: float) -> TrafficLevel:
    if factor <= LOW_TRAFFIC_MAX:
        return "Low"
    return "Moderate" if factor <= MODERATE_TRAFFIC_MAX else "High"


def timetable_seconds(direction: RouteDirection, d_from: float, d_to: float) -> float | None:
    """Planned seconds between two positions from the timetable, or None if there is none."""
    if direction.stops[-1].scheduled_offset_s <= 0:
        return None
    return max(0.0, scheduled_offset_at(direction, d_to) - scheduled_offset_at(direction, d_from))


def delay_factor(state: BusState, direction: RouteDirection) -> float:
    """Pace correction from the tracked schedule delay (1.0 = on time). See module docstring."""
    if state.status not in (BusStatus.EN_ROUTE, BusStatus.DWELLING):
        return 1.0
    elapsed = scheduled_offset_at(direction, state.distance_along_m)
    ratio = state.delay_s / max(elapsed, MIN_ELAPSED_FOR_PACE_S)
    return min(max(1.0 + ratio, DELAY_FACTOR_RANGE[0]), DELAY_FACTOR_RANGE[1])


def predict(
    sb: ServingBus,
    *,
    now: datetime,
    tz: ZoneInfo,
    profiles: dict[SegmentClass, TrafficProfile],
    table: DirectionClassTable,
    radius_m: float,
    scheduled_start: datetime | None = None,
    stale: bool = False,
) -> EtaPrediction:
    """Deterministic ETA for a bus that SERVES the stop (``sb.match`` is required)."""
    m = sb.match
    if m is None:
        raise ValueError("predict() needs a Feature 4 match — the bus must serve the stop")
    state, direction = sb.state, sb.position.direction
    d_factor = delay_factor(state, direction)

    def done(status: EtaStatus, eta: float | None) -> EtaPrediction:
        return EtaPrediction(
            status=status,
            computed_at=now,
            eta_s=eta,
            confidence="high",  # tracked facts, not forecasts
            traffic_level="Low",
            traffic_factor=1.0,
            delay_factor=round(d_factor, 3),
        )

    if m.proximity is StopProximity.AT_STOP:
        return done("at_stop", 0.0)
    if state.status is BusStatus.COMPLETED:
        return done("completed", None)
    if m.proximity is StopProximity.PASSED_STOP:
        return done("passed", None)

    D = float(m.distance_to_stop_m or 0.0)
    bus_d = state.distance_along_m
    stop_d = m.stop.distance_along_m

    # Waiting at the first stop for the scheduled departure?
    wait = 0.0
    if state.status is BusStatus.AT_DEPOT and scheduled_start is not None:
        wait = max(0.0, (scheduled_start - now).total_seconds())
    when = (now + timedelta(seconds=wait)).astimezone(tz)
    sod = when.hour * 3600 + when.minute * 60 + when.second

    # Road-class-aware traffic model over the remaining route.
    by_class = table.between(bus_d, stop_d)
    free_time = sum(dist / profiles[c].free_flow_mps for c, dist in by_class.items() if dist > 0)
    model_time = sum(
        dist / (profiles[c].free_flow_mps * profiles[c].factor_at(sod))
        for c, dist in by_class.items()
        if dist > 0
    )
    t_factor = model_time / free_time if free_time > 0 else 1.0
    v_model = D / model_time if model_time > 0 else MIN_EFFECTIVE_MPS

    moving = state.status is BusStatus.EN_ROUTE and state.speed_mps >= MOVING_MPS
    w = (NEAR_CURRENT_SPEED_WEIGHT if D <= NEAR_BLEND_M else FAR_CURRENT_SPEED_WEIGHT) if moving else 0.0
    v_eff = min(max(w * state.speed_mps + (1 - w) * v_model, MIN_EFFECTIVE_MPS), MAX_EFFECTIVE_MPS)
    travel = D / v_eff

    dwell = sum(
        s.dwell_s for s in direction.stops if bus_d + radius_m < s.distance_along_m < stop_d - radius_m
    )
    at_now = sb.position.at_stop
    if state.status is BusStatus.DWELLING and at_now is not None and at_now.stop_id != m.stop.stop_id:
        dwell += CURRENT_DWELL_SHARE * at_now.dwell_s

    timetable = timetable_seconds(direction, bus_d, stop_d)
    model_total = travel + dwell
    combined = (
        MODEL_WEIGHT * model_total + TIMETABLE_WEIGHT * timetable * d_factor
        if timetable is not None
        else model_total
    )

    score = 0
    score += 1 if moving or state.status is BusStatus.DWELLING else 0
    score += 1 if timetable is not None else 0
    score += 1 if all(c in profiles for c in SegmentClass) else 0
    score += 1 if D <= NEAR_STOP_M or (m.stops_away is not None and m.stops_away <= 2) else 0
    score -= 2 if stale else 0
    score -= 1 if wait > 0 else 0
    confidence: Confidence = "high" if score >= 3 else "medium" if score == 2 else "low"

    return EtaPrediction(
        status="predicted",
        computed_at=now,
        eta_s=wait + combined,
        confidence=confidence,
        traffic_level=traffic_level(t_factor),
        traffic_factor=round(t_factor, 3),
        delay_factor=round(d_factor, 3),
        travel_s=round(travel, 1),
        dwell_s=round(dwell, 1),
        wait_s=round(wait, 1),
        timetable_s=None if timetable is None else round(timetable, 1),
        history_source="timetable" if timetable is not None else None,
    )


def arrival_sort_key(item: tuple[ServingBus, EtaPrediction]) -> tuple:
    sb, p = item
    return (_STATUS_ORDER[p.status], p.eta_s if p.eta_s is not None else math.inf, sb.bus.id)


# =========================================================================== service


@dataclass(frozen=True)
class StudentArrivals:
    assignment: ResolvedAssignment
    my_bus: tuple[ServingBus, EtaPrediction | None] | None
    """The assigned bus; prediction is None when it is not serving the stop right now."""
    arrivals: list[tuple[ServingBus, EtaPrediction]]
    """Every bus serving the boarding stop in the assigned direction, ordered by ETA."""


class EtaService:
    """Builds predictions from Feature 4 matching + tracked state (cached static data)."""

    def __init__(
        self, repos: Repositories, settings: Settings, clock: Clock, matching: MatchingService
    ) -> None:
        self._repos = repos
        self._settings = settings
        self._clock = clock
        self._matching = matching
        self._profiles: dict[SegmentClass, TrafficProfile] | None = None
        self._tables: dict[str, DirectionClassTable] = {}

    async def _traffic(self) -> dict[SegmentClass, TrafficProfile]:
        if self._profiles is None:
            self._profiles = {SegmentClass(p.id): p for p in await self._repos.traffic_profiles.list()}
        return self._profiles

    def _table(self, sb: ServingBus) -> DirectionClassTable:
        key = sb.position.direction.variant_id
        if key not in self._tables:
            self._tables[key] = DirectionClassTable(sb.route, sb.position.direction)
        return self._tables[key]

    async def predict(self, sb: ServingBus) -> EtaPrediction:
        now = self._clock.now()
        start = None
        if sb.state.status is BusStatus.AT_DEPOT and sb.state.trip_id:
            trip = await self._repos.trips.get(sb.state.trip_id)
            start = trip.scheduled_start if trip else None
        stale = (now - sb.state.last_seen).total_seconds() > self._settings.bus_stale_after_s
        return predict(
            sb,
            now=now,
            tz=self._clock.tz,
            profiles=await self._traffic(),
            table=self._table(sb),
            radius_m=self._settings.stop_arrival_radius_m,
            scheduled_start=start,
            stale=stale,
        )

    async def bus_eta(self, bus_id: str, stop_id: str) -> tuple[ServingBus, EtaPrediction]:
        bus = await self._repos.buses.get(bus_id)
        if bus is None:
            raise NotFoundError(f"bus {bus_id} not found")
        if await self._repos.stops.get(stop_id) is None:
            raise NotFoundError(f"stop {stop_id} not found")
        state = await self._repos.bus_states.get(bus_id)
        if state is None:
            raise ConflictError(f"bus {bus_id} has no live state (not reporting / between trips)")
        sb = await self._matching.position_of(bus, state, stop_id)
        if sb is None or sb.match is None:
            running = state.variant_id or "no trip"
            raise ConflictError(f"bus {bus_id} is running {running}, which does not serve stop {stop_id}")
        return sb, await self.predict(sb)

    async def stop_arrivals(
        self, stop_id: str, *, direction: Direction | None = None
    ) -> list[tuple[ServingBus, EtaPrediction]]:
        serving = await self._matching.buses_serving_stop(stop_id, direction=direction)
        return sorted([(sb, await self.predict(sb)) for sb in serving], key=arrival_sort_key)

    async def student_arrivals(self, student_id: str) -> StudentArrivals | None:
        result = await self._matching.for_student(student_id)
        if result is None:
            return None
        serving = [*result.others, *([result.my_bus] if result.my_bus and result.my_bus.match else [])]
        arrivals = sorted([(sb, await self.predict(sb)) for sb in serving], key=arrival_sort_key)
        mine: tuple[ServingBus, EtaPrediction | None] | None = None
        if result.my_bus is not None:
            pred = next((p for sb, p in arrivals if sb.bus.id == result.my_bus.bus.id), None)
            mine = (result.my_bus, pred)
        return StudentArrivals(assignment=result.assignment, my_bus=mine, arrivals=arrivals)

    def forget_caches(self) -> None:
        self._profiles = None
        self._tables.clear()
