"""Missed-bus recovery (Feature 9) — other buses the student can catch at THEIR assigned stop.

Recovery suggestions never change the student's college-assigned bus.

Everything is reused; this module only adds the trigger, the screening and the ranking:

  CommuteDecisionService.for_student (Feature 7)
     ├─ decision YES / RISK / MISSED for the ASSIGNED bus, walking distance + speed,
     │  safety buffer, synthetic location                         → trigger, catch check
     └─ Feature 6 options  = Feature 5 ETAs of the buses Feature 4 matched to the
        ASSIGNED stop in the ASSIGNED direction (passed / completed already excluded)
        + live occupancy from Feature 8 (``BusState.occupancy``)  → candidates

Trigger (first match):  MISSED → ``missed`` · RISK → ``likely_to_miss`` ·
  assigned bus serving the stop and ≥ ``RECOVERY_DELAY_THRESHOLD_S`` late →
  ``significantly_delayed`` · otherwise no recovery (``not_needed``). The commute
  decision itself is never changed.

Screening — a candidate must be a Feature 6 option (so it serves the exact
boarding stop in the assigned direction and has not passed it / finished) and:
  not the assigned bus · arriving in the future (not already standing at the stop)
  · live data not stale · not broken down / off route · not full (Feature 8).

Catch check — Feature 7's own ``evaluate_commute`` with the candidate in place of
the assigned bus: YES → catchable; RISK → not catchable (too late, dropped);
LOCATION_UNAVAILABLE / UNKNOWN → catchability unknown (kept, never claimed).

Ranking (``rank_key``), ascending:
  1. catchable (True) before unknown       2. ETA (seconds)
  3. occupancy %  (unknown capacity last)  4. on time before delayed
  5. distance to the stop along the route  6. bus id
No score is computed or exposed. The first candidate is ``recommended``; up to
``RECOVERY_MAX_ALTERNATIVES`` more follow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.clock import Clock
from app.core.config import Settings
from app.models.common import BusStatus
from app.services.bus_comparison_service import BusOption
from app.services.capacity import available_seats, is_full, occupancy_percentage_display
from app.services.commute_decision_service import (
    AssignedBus,
    CommuteDecision,
    CommuteDecisionService,
    StudentCommute,
    evaluate_commute,
)
from app.services.tracking import is_delayed

Trigger = Literal["missed", "likely_to_miss", "significantly_delayed"]
Status = Literal["recovery_available", "not_needed", "no_alternative"]
ExcludeReason = Literal[
    "assigned_bus",
    "at_stop_now",
    "stale",
    "breakdown",
    "off_route",
    "full",
    "too_late",
    "passed_stop",
    "trip_completed",
]


def recovery_trigger(
    decision: str, *, assigned_serving: bool, assigned_delay_s: int | None, threshold_s: float
) -> Trigger | None:
    """Why recovery is offered (None = not needed). Consumes Feature 7's decision as-is."""
    if decision == "MISSED":
        return "missed"
    if decision == "RISK":
        return "likely_to_miss"
    if assigned_serving and assigned_delay_s is not None and assigned_delay_s >= threshold_s:
        return "significantly_delayed"
    return None


def screen(o: BusOption, *, now: datetime) -> ExcludeReason | None:
    """Exclusion reason for a Feature 6 option, or None if it may be offered."""
    s = o.sb.state
    if o.assigned:
        return "assigned_bus"
    if o.prediction.status != "predicted" or o.prediction.estimated_arrival is None:
        return "at_stop_now"
    if o.prediction.estimated_arrival <= now:
        return "at_stop_now"
    if o.stale:
        return "stale"
    if s.status is BusStatus.BREAKDOWN:
        return "breakdown"
    if s.status is BusStatus.DEVIATED:
        return "off_route"
    if is_full(s.occupancy, o.sb.bus.capacity):
        return "full"
    return None


@dataclass(frozen=True)
class Candidate:
    option: BusOption
    catch: CommuteDecision
    """Feature 7's evaluation of this bus for this student."""

    @property
    def bus_id(self) -> str:
        return self.option.bus_id

    @property
    def catchable(self) -> bool | None:
        d = self.catch.decision
        return True if d == "YES" else False if d in ("RISK", "MISSED") else None

    @property
    def eta_s(self) -> float:
        return self.option.prediction.eta_s or 0.0

    @property
    def spare_minutes(self) -> int | None:
        """Whole minutes the student would wait at the stop before this bus (floor)."""
        return None if self.catch.spare_s is None else math.floor(self.catch.spare_s / 60)

    @property
    def delayed(self) -> bool:
        return is_delayed(self.option.sb.state)

    @property
    def distance_m(self) -> float:
        m = self.option.sb.match
        return m.distance_to_stop_m if m is not None and m.distance_to_stop_m is not None else math.inf


def assess(
    o: BusOption,
    *,
    now: datetime,
    walking_distance_m: float | None,
    walking_speed_mps: float,
    buffer_s: float,
) -> Candidate:
    """Can the student catch this bus? — Feature 7's rules, unchanged."""
    s = o.sb.state
    catch = evaluate_commute(
        now=now,
        bus=AssignedBus(status=s.status, prediction=o.prediction, stale=o.stale, delay_s=s.delay_s),
        walking_distance_m=walking_distance_m,
        walking_speed_mps=walking_speed_mps,
        safety_buffer_s=buffer_s,
    )
    return Candidate(option=o, catch=catch)


def rank_key(c: Candidate) -> tuple:
    """catchable → ETA → occupancy % → on time → distance → bus id (all ascending)."""
    pct = c.option.occupancy_pct
    return (
        0 if c.catchable else 1,
        c.eta_s,
        pct if pct is not None else math.inf,
        1 if c.delayed else 0,
        c.distance_m,
        c.bus_id,
    )


def _a(n: int) -> str:
    """Article for a spoken number: "an 8-minute", "an 11-minute", "a 5-minute"."""
    s = str(n)
    return (
        "an"
        if s.startswith("8") or s in ("11", "18") or (len(s) in (5, 6) and s[:2] in ("11", "18"))
        else "a"
    )


def reason_for(c: Candidate, *, recommended: bool, sooner_too_late: bool, quietest: bool) -> str:
    """Plain-language reason built only from this candidate's actual values."""
    n = c.option.sb.bus.id
    eta = c.option.prediction.eta_minutes
    when = f"arrives in {eta} min" if eta else "is arriving now"
    if c.catchable is None:
        return (
            f"Bus {n} serves your stop and {when}. "
            "Your location is unavailable, so catching it can't be confirmed."
        )
    spare = c.spare_minutes or 0
    if recommended and sooner_too_late:
        return (
            f"Bus {n} is the next catchable bus serving your stop "
            f"and gives you {_a(spare)} {spare}-minute safety buffer."
        )
    if not recommended and quietest:
        return (
            f"Bus {n} is less crowded and still gives you enough time "
            f"to reach the stop ({spare} min to spare)."
        )
    return f"Bus {n} serves your stop and gives you {_a(spare)} {spare}-minute safety buffer."


@dataclass(frozen=True)
class RecoveryOption:
    candidate: Candidate
    reason: str

    @property
    def available_seats(self) -> int:
        s = self.candidate.option.sb
        return available_seats(s.state.occupancy, s.bus.capacity)

    @property
    def occupancy_percentage(self) -> int | None:
        s = self.candidate.option.sb
        return occupancy_percentage_display(s.state.occupancy, s.bus.capacity)


@dataclass(frozen=True)
class Excluded:
    bus_id: str
    reason: ExcludeReason


@dataclass(frozen=True)
class Recovery:
    status: Status
    trigger: Trigger | None
    recommended: RecoveryOption | None
    alternatives: list[RecoveryOption]
    excluded: list[Excluded]


def plan_recovery(
    commute: StudentCommute,
    *,
    now: datetime,
    delay_threshold_s: float,
    buffer_s: float,
    max_alternatives: int,
) -> Recovery:
    """Pure recovery plan from a Feature 7 result (which carries the Feature 6 options)."""
    sb = commute.my_bus
    trigger = recovery_trigger(
        commute.result.decision,
        assigned_serving=commute.prediction is not None and commute.prediction.status == "predicted",
        assigned_delay_s=sb.state.delay_s if sb is not None else None,
        threshold_s=delay_threshold_s,
    )
    if trigger is None:
        return Recovery("not_needed", None, None, [], [])

    cmp = commute.options.comparison
    excluded = [
        Excluded(x.sb.bus.id, "passed_stop" if x.reason == "passed_stop" else "trip_completed")
        for x in cmp.excluded
        if x.sb.bus.id != commute.assignment.bus.id
    ]
    viable: list[Candidate] = []
    too_late: list[Candidate] = []
    for o in cmp.options:
        why = screen(o, now=now)
        if why is not None:
            if why != "assigned_bus":
                excluded.append(Excluded(o.bus_id, why))
            continue
        c = assess(
            o,
            now=now,
            walking_distance_m=commute.walking_distance_m,
            walking_speed_mps=commute.walking_speed_mps,
            buffer_s=buffer_s,
        )
        if c.catchable is False:
            too_late.append(c)
            excluded.append(Excluded(c.bus_id, "too_late"))
        else:
            viable.append(c)

    ranked = sorted(viable, key=rank_key)
    if not ranked:
        return Recovery("no_alternative", trigger, None, [], sorted(excluded, key=lambda x: x.bus_id))
    first, rest = ranked[0], ranked[1 : 1 + max(max_alternatives, 0)]
    sooner_too_late = any(t.eta_s < first.eta_s for t in too_late)
    least = min((c.option.occupancy_pct for c in ranked if c.option.occupancy_pct is not None), default=None)

    def option(c: Candidate, recommended: bool) -> RecoveryOption:
        quietest = (
            least is not None
            and c.option.occupancy_pct == least
            and first.option.occupancy_pct is not None
            and least < first.option.occupancy_pct
        )
        return RecoveryOption(
            c, reason_for(c, recommended=recommended, sooner_too_late=sooner_too_late, quietest=quietest)
        )

    return Recovery(
        "recovery_available",
        trigger,
        option(first, True),
        [option(c, False) for c in rest],
        sorted(excluded, key=lambda x: x.bus_id),
    )


# =========================================================================== service


@dataclass(frozen=True)
class StudentRecovery:
    commute: StudentCommute
    recovery: Recovery
    computed_at: datetime


class MissedBusService:
    def __init__(self, commute: CommuteDecisionService, settings: Settings, clock: Clock) -> None:
        self._commute = commute
        self._settings = settings
        self._clock = clock

    async def for_student(self, student_id: str) -> StudentRecovery | None:
        """Recovery for the student's ASSIGNED bus at the ASSIGNED stop; None if unassigned."""
        commute = await self._commute.for_student(student_id)
        if commute is None:
            return None
        return self._plan(commute)

    async def for_students(self, student_ids: list[str]) -> list[StudentRecovery]:
        """Same recovery for many students (Feature 11 alert sweep; shared comparisons)."""
        return [self._plan(c) for c in await self._commute.for_students(student_ids)]

    def _plan(self, commute: StudentCommute) -> StudentRecovery:
        now = self._clock.now()
        recovery = plan_recovery(
            commute,
            now=now,
            delay_threshold_s=self._settings.recovery_delay_threshold_s,
            buffer_s=self._settings.commute_safety_buffer_s,
            max_alternatives=self._settings.recovery_max_alternatives,
        )
        return StudentRecovery(commute=commute, recovery=recovery, computed_at=now)
