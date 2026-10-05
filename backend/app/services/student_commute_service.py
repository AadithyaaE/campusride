"""Student commute experience (Feature 16): today's commute + commute history.

Read models over the EXISTING services — nothing is predicted, scored or decided here:

* **Today** composes, for the authenticated student, the Feature 9 recovery chain (which
  carries the Feature 7 decision, the Feature 5 prediction and the Feature 4 position of the
  assigned bus), the Feature 8 boarding state, the stored trip, the bus's live DTO and the
  student's own active Feature 11 alerts. The only new rule is ``commute_phase``: one label
  ("waiting", "approaching", "on board", …) chosen from those backend results.
* **History** is derived on read from authoritative records — trips, boarding events and the
  student's MISSED_BUS alerts — in a fixed number of indexed queries (no per-trip lookups,
  no second copy of the data). Scheduled trips that never started (e.g. a driver-controlled
  bus still waiting for Start Trip) are not history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.auth import Principal
from app.core.clock import Clock
from app.models import Alert, BoardingEvent, Bus, BusState, Route, Stop, Trip
from app.models.common import AlertType, StopProximity, TripStatus
from app.repositories import Repositories
from app.services.alert_service import AlertService
from app.services.assignments import AssignmentService, ResolvedAssignment
from app.services.boarding_service import BoardingService, StudentBoarding
from app.services.commute_decision_service import REASON
from app.services.missed_bus_service import MissedBusService, StudentRecovery

Phase = Literal[
    "unassigned",
    "no_trip",
    "waiting",
    "approaching",
    "at_stop",
    "on_board",
    "completed",
    "missed",
    "recovery_available",
]
Outcome = Literal["boarded", "in_progress", "missed", "ended_early", "no_boarding_recorded", "cancelled"]
STARTED = (TripStatus.ACTIVE, TripStatus.COMPLETED)


def commute_phase(
    *,
    assigned: bool,
    on_commute: bool,
    trip: Trip | None,
    boarded: bool,
    decision: str | None,
    recovery_available: bool,
    proximity: StopProximity | None,
) -> tuple[Phase, str]:
    """One label for the student's commute right now, from backend results (first match wins)."""
    if not assigned:
        return "unassigned", "Your college transport office hasn't assigned you a bus yet."
    if not on_commute or trip is None:
        return "no_trip", "Your bus has no trip to your stop running right now."
    if boarded:
        if trip.status is TripStatus.COMPLETED:
            return "completed", "You boarded this trip and it has finished."
        return "on_board", "You're on board — the trip is in progress."
    started = trip.status in STARTED
    if decision == "MISSED" and started:  # never for a trip that hasn't started (Feature 14 fix)
        if recovery_available:
            return "recovery_available", "You've missed your bus — another bus can still get you there."
        return "missed", "You've missed your bus for this trip."
    if trip.status is TripStatus.COMPLETED:
        return "no_trip", "Your bus has finished this trip."
    if proximity is StopProximity.AT_STOP:
        return "at_stop", "Your bus is at your stop now."
    if proximity is StopProximity.APPROACHING_STOP:
        return "approaching", "Your bus is approaching your stop."
    if not started:
        return "waiting", "Your bus hasn't departed yet."
    return "waiting", "Your bus is on its way."


@dataclass(frozen=True)
class StudentCommuteView:
    student_id: str
    recovery: StudentRecovery | None
    boarding: StudentBoarding | None
    trip: Trip | None
    phase: Phase
    phase_reason: str
    bus: Bus | None
    state: BusState | None
    alerts: list[Alert]
    computed_at: datetime


@dataclass(frozen=True)
class HistoryEntry:
    trip: Trip
    route: Route | None
    boarding_stop: Stop | None
    outcome: Outcome
    boarded: BoardingEvent | None
    missed_alert: Alert | None


def history_outcome(trip: Trip, boarded: BoardingEvent | None, missed: Alert | None) -> Outcome:
    """What the stored records say about one started trip for this student."""
    if boarded is not None:
        return "boarded"
    if trip.status is TripStatus.ACTIVE:
        return "in_progress"
    if trip.status is TripStatus.CANCELLED:
        return "cancelled"
    reason = missed.payload.get("reason") if missed is not None else None
    if trip.end_reason == "driver_stop" and (missed is None or reason == REASON["completed"]):
        return "ended_early"  # the driver stopped before the bus reached the student's stop
    if missed is not None:
        return "missed"
    return "no_boarding_recorded"


class StudentCommuteService:
    def __init__(
        self,
        repos: Repositories,
        clock: Clock,
        recovery: MissedBusService,
        boarding: BoardingService,
        alerts: AlertService,
    ) -> None:
        self._repos = repos
        self._clock = clock
        self._recovery = recovery
        self._boarding = boarding
        self._alerts = alerts

    async def today(self, principal: Principal) -> StudentCommuteView:
        sid = principal.user_id
        sr = await self._recovery.for_student(sid)
        alerts = await self._alerts.list_for(principal, active=True, limit=20)
        now = self._clock.now()
        if sr is None:
            phase, reason = commute_phase(
                assigned=False, on_commute=False, trip=None, boarded=False,
                decision=None, recovery_available=False, proximity=None,
            )  # fmt: skip
            return StudentCommuteView(sid, None, None, None, phase, reason, None, None, alerts, now)
        a = sr.commute.assignment
        boarding = await self._boarding.for_student(sid)
        state = await self._repos.bus_states.get(a.bus.id)
        on_commute = state is not None and state.variant_id == a.direction.variant_id
        trip = await self._repos.trips.get(state.trip_id) if state is not None and state.trip_id else None
        sb = sr.commute.my_bus
        phase, reason = commute_phase(
            assigned=True,
            on_commute=on_commute,
            trip=trip,
            boarded=boarding is not None and boarding.boarded is not None,
            decision=sr.commute.result.decision,
            recovery_available=sr.recovery.status == "recovery_available",
            proximity=sb.match.proximity if sb is not None and sb.match is not None else None,
        )
        return StudentCommuteView(sid, sr, boarding, trip, phase, reason, a.bus, state, alerts, now)

    async def history(self, student_id: str, *, limit: int = 20) -> list[HistoryEntry]:
        """The student's started trips, newest first (deterministic order: departure, trip id)."""
        repos = self._repos
        assigned: ResolvedAssignment | None = await AssignmentService(repos).for_student(student_id)
        trips: dict[str, Trip] = {}
        if assigned is not None:  # the assigned bus's trips in the assigned direction (index: bus_date)
            for t in await repos.trips.list(
                filter={"bus_id": assigned.bus.id, "variant_id": assigned.direction.variant_id}, limit=10_000
            ):
                trips[t.id] = t
        mine = await repos.boarding_events.list(filter={"student_id": student_id}, limit=10_000)
        boardings = {b.trip_id: b for b in mine}  # index: student_trip_unique
        missing = [tid for tid in boardings if tid not in trips]
        for t in await repos.trips.get_many(missing) if missing else []:
            trips[t.id] = t
        missed: dict[str, Alert] = {}  # index: recipient_user_created (newest first)
        for alert in await repos.alerts.for_recipient(user_id=student_id, limit=10_000):
            if alert.type is AlertType.MISSED_BUS and alert.trip_id and alert.trip_id not in missed:
                missed[alert.trip_id] = alert
        started = sorted(
            (t for t in trips.values() if t.status is not TripStatus.SCHEDULED or t.id in boardings),
            key=lambda t: (t.scheduled_start, t.id),
            reverse=True,
        )[:limit]
        routes = {r.id: r for r in await repos.routes.get_many(sorted({t.route_id for t in started}))}
        stop_ids = {b.stop_id for b in boardings.values()}
        if assigned is not None:
            stop_ids.add(assigned.boarding_stop.id)
        stops = {s.id: s for s in await repos.stops.get_many(sorted(stop_ids))}
        out: list[HistoryEntry] = []
        for t in started:
            b = boardings.get(t.id)
            on_assigned = assigned is not None and t.variant_id == assigned.direction.variant_id
            stop_id = b.stop_id if b else (assigned.boarding_stop.id if assigned and on_assigned else None)
            out.append(
                HistoryEntry(
                    trip=t,
                    route=routes.get(t.route_id),
                    boarding_stop=stops.get(stop_id) if stop_id else None,
                    outcome=history_outcome(t, b, missed.get(t.id)),
                    boarded=b,
                    missed_alert=missed.get(t.id),
                )
            )
        return out
