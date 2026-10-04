""" "Will I make my bus?" — deterministic commute decision (Feature 7). No ML, no probability.

Question: can the student reach their ASSIGNED boarding stop before their
ASSIGNED bus arrives, with a safety buffer?

Inputs, all reused:
  assignment            bus / route direction / boarding stop (college-assigned)
  Feature 4 matching    is the bus serving the stop; passed / at stop / approaching
  Feature 5 ETA         the bus's estimated arrival time (delay ALREADY included)
  Feature 6 comparison  only to say whether alternatives exist (never chosen here)
  tracked BusState      status (dwelling, breakdown, deviated…), staleness
  student location      synthetic demo location (``student_location.py``) — no GPS
  walking distance      ``geo.walking_distance_m``: straight line × 1.3 street detour
  walking speed         the student's profile speed, else ``WALKING_SPEED_MPS``

Rules, first match wins (timestamps internally, never rounded minutes):
  1. no live state for the bus                       → UNKNOWN  (assigned bus unavailable)
  2. not serving the stop in the assigned direction  → MISSED   (between trips / other way)
  3. Feature 5 status ``passed``                      → MISSED
     Feature 5 status ``completed``                   → MISSED
  4. no ETA, or arrival time already elapsed          → UNKNOWN / MISSED
  5. no student location                             → LOCATION_UNAVAILABLE
  6. walking speed ≤ 0 / not finite                   → UNKNOWN
  7. timing:   student_arrival  = now + walk_distance / walk_speed
               required_arrival = bus_arrival − SAFETY_BUFFER
       student_arrival <  required_arrival  → YES
       otherwise                            → RISK  (the bus has not passed: never MISSED)
     Boundary: EXACT equality is RISK (walk + buffer ≥ ETA → RISK).
  8. a YES is downgraded to RISK (never upgraded) when the bus is broken down,
     off route, or its telemetry is stale (> ``BUS_STALE_AFTER_S``).

Delay is not added again: Feature 5's ETA already contains it; ``delay_s`` is
exposed for explanation only. YES / RISK / MISSED are the three decisions;
LOCATION_UNAVAILABLE and UNKNOWN say a decision can't be made.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from app.core.clock import Clock
from app.core.config import Settings
from app.geo import walking_distance_m
from app.models.assignment import StudentAssignment
from app.models.common import BusStatus
from app.repositories import Repositories
from app.services.assignments import ResolvedAssignment
from app.services.bus_comparison_service import BusComparisonService, StudentBusOptions
from app.services.eta_service import EtaPrediction
from app.services.matching import ServingBus
from app.services.student_location import StudentLocation, StudentLocationSource
from app.services.tracking import is_stale

Decision = Literal["YES", "RISK", "MISSED", "LOCATION_UNAVAILABLE", "UNKNOWN"]

REASON = {
    "yes": "You should reach your stop before the bus.",
    "tight": "You may reach the stop, but there is little time to spare.",
    "late": "The bus is due before you can reach the stop.",
    "at_stop_go": "Your bus is at the stop now — go straight there.",
    "at_stop": "Your bus is at the stop now and may leave before you get there.",
    "stale": "Bus location is not updating, so arrival timing is uncertain.",
    "breakdown": "Your bus has reported a breakdown, so it may not arrive as predicted.",
    "deviated": "Your bus is off its usual route, so arrival timing is uncertain.",
    "passed": "Your assigned bus has already passed your stop.",
    "completed": "Your assigned bus has finished this trip.",
    "not_serving": "Your assigned bus is no longer serving your stop.",
    "elapsed": "Your assigned bus's expected arrival time has already passed.",
    "no_bus": "No live data for your assigned bus yet, so we can't tell.",
    "no_eta": "No arrival estimate for your bus yet, so we can't tell.",
    "no_location": "Your location is unavailable, so your walking time can't be estimated.",
    "bad_speed": "Walking speed is not set, so your walking time can't be estimated.",
}


@dataclass(frozen=True)
class AssignedBus:
    """What the decision needs to know about the assigned bus (from Features 4/5 + tracking)."""

    status: BusStatus
    prediction: EtaPrediction | None
    """None = the bus is not serving the boarding stop in the assigned direction."""
    stale: bool
    delay_s: int


@dataclass(frozen=True)
class CommuteDecision:
    decision: Decision
    reason: str
    computed_at: datetime
    walking_distance_m: float | None = None
    walking_speed_mps: float | None = None
    walking_time_s: float | None = None
    bus_eta_s: float | None = None
    bus_arrival_time: datetime | None = None
    required_arrival_time: datetime | None = None
    student_arrival_time: datetime | None = None
    safety_buffer_s: float = 0.0

    @property
    def walking_time_minutes(self) -> int | None:
        """Whole minutes, rounded UP (0 = under a minute) — conservative for the walker."""
        return None if self.walking_time_s is None else _ceil_min(self.walking_time_s)

    @property
    def bus_eta_minutes(self) -> int | None:
        return None if self.bus_eta_s is None else _ceil_min(self.bus_eta_s)

    @property
    def spare_s(self) -> float | None:
        """Time between reaching the stop and the bus arriving (negative = bus first)."""
        if self.bus_arrival_time is None or self.student_arrival_time is None:
            return None
        return (self.bus_arrival_time - self.student_arrival_time).total_seconds()


def _ceil_min(seconds: float) -> int:
    return 0 if seconds < 60 else math.ceil(seconds / 60 - 1e-9)


def walking_time_s(distance_m: float, speed_mps: float) -> float | None:
    """None for a zero / negative / non-finite speed (never divide by it)."""
    if not (math.isfinite(speed_mps) and speed_mps > 0) or not math.isfinite(distance_m):
        return None
    return max(distance_m, 0.0) / speed_mps


def evaluate_commute(
    *,
    now: datetime,
    bus: AssignedBus | None,
    walking_distance_m: float | None,
    walking_speed_mps: float,
    safety_buffer_s: float,
) -> CommuteDecision:
    """Pure decision for the ASSIGNED bus. See the module docstring for the rule order."""
    buffer = max(safety_buffer_s, 0.0)

    def done(decision: Decision, key: str, **kw) -> CommuteDecision:
        return CommuteDecision(decision, REASON[key], now, safety_buffer_s=buffer, **kw)

    # ---- bus side first: a bus that is gone is MISSED wherever the student is
    if bus is None:
        return done("UNKNOWN", "no_bus")
    p = bus.prediction
    if p is None:
        return done("MISSED", "not_serving")
    if p.status == "passed":
        return done("MISSED", "passed")
    if p.status == "completed":
        return done("MISSED", "completed")
    arrival = p.estimated_arrival
    if p.eta_s is None or arrival is None or not math.isfinite(p.eta_s):
        return done("UNKNOWN", "no_eta")
    eta_s = max((arrival - now).total_seconds(), 0.0)
    timing = {"bus_eta_s": eta_s, "bus_arrival_time": arrival}
    if p.status == "predicted" and arrival < now:
        return done("MISSED", "elapsed", **timing)

    # ---- student side
    if walking_distance_m is None:
        return done("LOCATION_UNAVAILABLE", "no_location", **timing)
    walk_s = walking_time_s(walking_distance_m, walking_speed_mps)
    if walk_s is None:
        return done("UNKNOWN", "bad_speed", walking_distance_m=walking_distance_m, **timing)

    student_arrival = now + timedelta(seconds=walk_s)
    required = arrival - timedelta(seconds=buffer)
    detail = {
        **timing,
        "walking_distance_m": walking_distance_m,
        "walking_speed_mps": walking_speed_mps,
        "walking_time_s": walk_s,
        "required_arrival_time": required,
        "student_arrival_time": student_arrival,
    }
    if student_arrival < required:
        # ---- conservative downgrades: never a confident YES on doubtful bus data
        if bus.status is BusStatus.BREAKDOWN:
            return done("RISK", "breakdown", **detail)
        if bus.stale:
            return done("RISK", "stale", **detail)
        if bus.status is BusStatus.DEVIATED:
            return done("RISK", "deviated", **detail)
        return done("YES", "yes", **detail)
    if bus.status is BusStatus.BREAKDOWN:
        return done("RISK", "breakdown", **detail)
    if bus.stale:
        return done("RISK", "stale", **detail)
    if p.status == "at_stop":
        return done("RISK", "at_stop_go" if walk_s <= 60 else "at_stop", **detail)
    return done("RISK", "tight" if student_arrival <= arrival else "late", **detail)


# =========================================================================== service


@dataclass(frozen=True)
class StudentCommute:
    assignment: ResolvedAssignment
    my_bus: ServingBus | None
    prediction: EtaPrediction | None
    """The assigned bus's Feature 5 prediction (None when it is not serving the stop)."""
    stale: bool
    location: StudentLocation | None
    result: CommuteDecision
    alternatives_available: int
    """Other buses (Feature 6 options) serving the stop — shown, never switched to."""
    options: StudentBusOptions
    """The Feature 6 comparison this decision was built from (reused by recovery, Feature 9)."""
    walking_distance_m: float | None
    """Feature 7 walk to the boarding stop (None without a location) — reused by recovery."""
    walking_speed_mps: float


class CommuteDecisionService:
    def __init__(
        self,
        comparison: BusComparisonService,
        repos: Repositories,
        settings: Settings,
        clock: Clock,
        locations: StudentLocationSource,
    ) -> None:
        self._comparison = comparison
        self._repos = repos
        self._settings = settings
        self._clock = clock
        self._locations = locations

    async def for_student(self, student_id: str) -> StudentCommute | None:
        """Decision for the student's ASSIGNED bus at their ASSIGNED stop; None if unassigned."""
        options = await self._comparison.for_student(student_id)
        if options is None:
            return None
        return await self._decide(student_id, options)

    async def for_students(self, student_ids: list[str]) -> list[StudentCommute]:
        """Same decisions for many students (Feature 11 alert sweep).

        Students with the same assigned bus, boarding stop and direction share one
        Feature 6 comparison (computed once per group); each student then gets the
        exact per-student decision of ``for_student`` (own location and walking speed).
        """
        groups: dict[tuple[str, str, str], list[StudentAssignment]] = {}
        for sa in await self._repos.student_assignments.get_many(student_ids):
            key = (sa.assigned_bus_id, sa.boarding_stop_id, sa.assigned_route_direction_id)
            groups.setdefault(key, []).append(sa)
        profiles = {p.id: p for p in await self._repos.student_profiles.get_many(student_ids)}
        out: list[StudentCommute] = []
        for members in groups.values():
            members.sort(key=lambda sa: sa.id)
            options = await self._comparison.for_student(members[0].id)
            if options is None:
                continue
            for sa in members:
                mine = replace(options, assignment=replace(options.assignment, assignment=sa))
                speed = (
                    profiles[sa.id].walk_speed_mps if sa.id in profiles else self._settings.walking_speed_mps
                )
                out.append(await self._decide(sa.id, mine, walking_speed_mps=speed))
        return sorted(out, key=lambda c: c.assignment.assignment.id)

    async def _decide(
        self, student_id: str, options: StudentBusOptions, *, walking_speed_mps: float | None = None
    ) -> StudentCommute:
        a = options.assignment
        now = self._clock.now()

        bus: AssignedBus | None = None
        sb: ServingBus | None = None
        if options.my_bus is not None:
            sb, pred = options.my_bus
            bus = AssignedBus(
                status=sb.state.status,
                prediction=pred,
                stale=is_stale(sb.state, now, self._settings.bus_stale_after_s),
                delay_s=sb.state.delay_s,
            )

        location = self._locations.locate(student_id, a.boarding_stop)
        distance = (
            walking_distance_m(location.point, tuple(a.boarding_stop.location.coordinates))
            if location is not None
            else None
        )
        if walking_speed_mps is None:
            profile = await self._repos.student_profiles.get(student_id)
            speed = profile.walk_speed_mps if profile is not None else self._settings.walking_speed_mps
        else:
            speed = walking_speed_mps

        result = evaluate_commute(
            now=now,
            bus=bus,
            walking_distance_m=distance,
            walking_speed_mps=speed,
            safety_buffer_s=self._settings.commute_safety_buffer_s,
        )
        alternatives = sum(1 for o in options.comparison.options if not o.assigned and o.comparable)
        return StudentCommute(
            assignment=a,
            my_bus=sb,
            prediction=bus.prediction if bus is not None else None,
            stale=bus.stale if bus is not None else False,
            location=location,
            result=result,
            alternatives_available=alternatives,
            options=options,
            walking_distance_m=distance,
            walking_speed_mps=speed,
        )
