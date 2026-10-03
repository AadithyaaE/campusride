"""QR boarding (Feature 8) — validate a scan against the college assignment, record it once.

PROTOTYPE: the QR payload is plain JSON ``{student_id, bus_id, trip_id, timestamp}``
built by a SIMULATED scanner in the student app. It is NOT signed and is not
secure authentication. ``read_qr`` is the single seam where a signed / rotating
token (``Bus.qr_secret``) can be verified later — the rules below don't change.

Validation, in order (the college assignment is authoritative, never the payload):
  1. caller is a student, and the payload's student is the caller     403 not_a_student / invalid_student
  2. the student exists and has an assignment                         404 invalid_student / 409 unassigned
  3. payload bus = the ASSIGNED bus                                   403 wrong_bus
  4. trip exists, belongs to that bus, runs the ASSIGNED direction     404 trip_not_found /
                                                                      409 bus_trip_mismatch, wrong_trip
  5. trip is boardable: scheduled/active AND the bus's current trip   409 trip_inactive
  6. stop (if sent) = the ASSIGNED boarding stop; the bus has not
     passed it (Feature 4 matching)                                   422 invalid_stop / 409 stop_passed
  7. already boarded this trip → ``already_boarded`` (200, nothing written)
  8. bus full (occupancy ≥ capacity)                                   409 bus_full
  9. insert the event ONCE (unique (student_id, trip_id); id ``BRD-<trip>-<student>``),
     then re-derive occupancy from the event COUNT (``capacity.py``). If a concurrent
     last-seat race overfilled the bus, this boarding is undone → bus_full.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.auth import Principal
from app.core.clock import Clock
from app.core.errors import CampusRideError
from app.core.events import EventBus
from app.models import BoardingEvent, Bus, BusState, Trip
from app.models.common import (
    BoardingSource,
    BoardingType,
    BusSource,
    BusStatus,
    Role,
    StopProximity,
    TripStatus,
)
from app.models.events import BoardingRecorded
from app.repositories import Repositories
from app.services.assignments import AssignmentService, ResolvedAssignment
from app.services.capacity import available_seats, is_full, occupancy_percentage_display
from app.services.matching import MatchingService
from app.services.tracking import TelemetryIngestService

BOARDABLE = (TripStatus.SCHEDULED, TripStatus.ACTIVE)


class BoardingRejected(CampusRideError):
    """A scan that must not be recorded. ``code`` tells the UI exactly why."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class QrPayload:
    student_id: str
    bus_id: str
    trip_id: str
    timestamp: datetime
    stop_id: str | None = None
    scanner: Literal["simulated", "camera"] = "simulated"


def read_qr(payload: QrPayload) -> QrPayload:
    """Prototype: the payload is taken as-is (unsigned). Verify a signed token here later."""
    return payload


def boarding_id(trip_id: str, student_id: str) -> str:
    """Server-derived, deterministic — never taken from the client."""
    return f"BRD-{trip_id}-{student_id}"


@dataclass(frozen=True)
class Occupancy:
    bus_id: str
    trip_id: str | None
    occupancy: int
    capacity: int
    baseline: int
    boarded: int
    source: Literal["synthetic_baseline+qr", "qr", "no_live_data"]
    updated_at: datetime | None

    @property
    def available_seats(self) -> int:
        return available_seats(self.occupancy, self.capacity)

    @property
    def occupancy_percentage(self) -> int | None:
        return occupancy_percentage_display(self.occupancy, self.capacity)


@dataclass(frozen=True)
class ScanResult:
    status: Literal["boarded", "already_boarded"]
    event: BoardingEvent
    occupancy: Occupancy


@dataclass(frozen=True)
class StudentBoarding:
    """What the scanner screen needs: assignment, current trip, readiness, occupancy."""

    assignment: ResolvedAssignment
    trip_id: str | None
    ready: bool
    reason_code: str | None
    reason: str | None
    boarded: BoardingEvent | None
    occupancy: Occupancy


@dataclass(frozen=True)
class TripBoarding:
    trip: Trip
    total_boarded: int
    events: list[BoardingEvent]
    visibility: Literal["all", "own", "count_only"]


def occupancy_of(bus: Bus, state: BusState | None) -> Occupancy:
    if state is None:
        return Occupancy(bus.id, None, 0, bus.capacity, 0, 0, "no_live_data", None)
    running = state.trip_id if state.status is not BusStatus.COMPLETED else None
    return Occupancy(
        bus_id=bus.id,
        trip_id=running,
        occupancy=state.occupancy,
        capacity=bus.capacity,
        baseline=state.occupancy_baseline,
        boarded=state.boarded_count,
        source="synthetic_baseline+qr" if bus.source is BusSource.SIM else "qr",
        updated_at=state.ts,
    )


class BoardingService:
    def __init__(
        self,
        repos: Repositories,
        clock: Clock,
        events: EventBus,
        matching: MatchingService,
        ingest: TelemetryIngestService,
    ) -> None:
        self._repos = repos
        self._clock = clock
        self._events = events
        self._matching = matching
        self._ingest = ingest

    # ------------------------------------------------------------------ validation

    async def _assignment(self, student_id: str) -> ResolvedAssignment:
        user = await self._repos.users.get(student_id)
        if user is None or user.role is not Role.STUDENT:
            raise BoardingRejected("invalid_student", f"{student_id} is not a known student", 404)
        a = await AssignmentService(self._repos).for_student(student_id)
        if a is None:
            raise BoardingRejected(
                "unassigned", "You have no bus assignment yet, so boarding can't be recorded."
            )
        return a

    async def _validate(self, qr: QrPayload) -> tuple[ResolvedAssignment, Bus, Trip, BusState]:
        a = await self._assignment(qr.student_id)
        if qr.bus_id != a.bus.id:
            raise BoardingRejected(
                "wrong_bus", f"This QR is for bus {qr.bus_id}, but your assigned bus is {a.bus.id}.", 403
            )
        trip = await self._repos.trips.get(qr.trip_id)
        if trip is None:
            raise BoardingRejected("trip_not_found", f"Trip {qr.trip_id} does not exist.", 404)
        if trip.bus_id != qr.bus_id:
            raise BoardingRejected(
                "bus_trip_mismatch", f"Trip {trip.id} is run by bus {trip.bus_id}, not {qr.bus_id}."
            )
        if trip.variant_id != a.direction.variant_id:
            raise BoardingRejected(
                "wrong_trip",
                f"Trip {trip.id} runs {trip.variant_id}; your assignment is {a.direction.variant_id}.",
            )
        state = await self._repos.bus_states.get(a.bus.id)
        if trip.status not in BOARDABLE or state is None or state.trip_id != trip.id:
            raise BoardingRejected(
                "trip_inactive", f"Trip {trip.id} is not currently boardable ({trip.status})."
            )
        if qr.stop_id is not None and qr.stop_id != a.boarding_stop.id:
            raise BoardingRejected(
                "invalid_stop", f"Your boarding stop is {a.boarding_stop.name}, not {qr.stop_id}.", 422
            )
        sb = await self._matching.position_of(a.bus, state, a.boarding_stop.id)
        if sb is None or sb.match is None or sb.match.proximity is StopProximity.PASSED_STOP:
            raise BoardingRejected(
                "stop_passed", f"Bus {a.bus.id} has already passed {a.boarding_stop.name}."
            )
        return a, a.bus, trip, state

    # ------------------------------------------------------------------ scan

    async def scan(self, principal: Principal, payload: QrPayload) -> ScanResult:
        if principal.role is not Role.STUDENT:
            raise BoardingRejected("not_a_student", "Only students can scan a boarding QR.", 403)
        qr = read_qr(payload)
        if qr.student_id != principal.user_id:
            raise BoardingRejected(
                "invalid_student", "This QR payload is not for the signed-in student.", 403
            )
        a, bus, trip, state = await self._validate(qr)

        existing = await self._repos.boarding_events.for_student_trip(qr.student_id, trip.id)
        if existing is not None:
            return ScanResult("already_boarded", existing, occupancy_of(bus, state))
        if is_full(state.occupancy, bus.capacity):
            raise BoardingRejected("bus_full", f"Bus {bus.id} is full — no seats are available.")

        event = BoardingEvent(
            id=boarding_id(trip.id, qr.student_id),
            trip_id=trip.id,
            bus_id=bus.id,
            stop_id=a.boarding_stop.id,  # from the assignment, not the browser
            student_id=qr.student_id,
            ts=self._clock.now(),
            type=BoardingType.BOARD,
            source=BoardingSource.QR,
            qr_ts=qr.timestamp,
            scanner=qr.scanner,
        )
        if not await self._repos.boarding_events.insert_once(event):  # concurrent duplicate
            again = await self._repos.boarding_events.for_student_trip(qr.student_id, trip.id)
            fresh = await self._repos.bus_states.get(bus.id)
            return ScanResult("already_boarded", again or event, occupancy_of(bus, fresh))

        fresh = await self._ingest.refresh_occupancy(bus.id)
        if fresh is not None and fresh.occupancy_baseline + fresh.boarded_count > bus.capacity:
            # Lost a last-seat race: undo this boarding, keep the bus at capacity.
            await self._repos.boarding_events.delete(event.id)
            await self._ingest.refresh_occupancy(bus.id)
            raise BoardingRejected("bus_full", f"Bus {bus.id} is full — no seats are available.")
        await self._events.publish(
            BoardingRecorded(
                ts=event.ts,
                trip_id=trip.id,
                bus_id=bus.id,
                stop_id=event.stop_id,
                type=BoardingType.BOARD,
                student_id=qr.student_id,
            )
        )
        return ScanResult("boarded", event, occupancy_of(bus, fresh))

    # ------------------------------------------------------------------ reads

    async def occupancy(self, bus_id: str) -> Occupancy:
        bus = await self._repos.buses.get(bus_id)
        if bus is None:
            raise BoardingRejected("bus_not_found", f"bus {bus_id} not found", 404)
        return occupancy_of(bus, await self._repos.bus_states.get(bus_id))

    async def for_student(self, student_id: str) -> StudentBoarding | None:
        """Scanner screen state for the student's ASSIGNED bus; None if unassigned."""
        a = await AssignmentService(self._repos).for_student(student_id)
        if a is None:
            return None
        state = await self._repos.bus_states.get(a.bus.id)
        trip_id = state.trip_id if state is not None else None
        boarded = await self._repos.boarding_events.for_student_trip(student_id, trip_id) if trip_id else None
        code: str | None = None
        reason: str | None = None
        if boarded is None:
            if trip_id is None:
                code, reason = "trip_inactive", f"Bus {a.bus.id} has no trip running right now."
            else:
                probe = QrPayload(student_id, a.bus.id, trip_id, self._clock.now(), a.boarding_stop.id)
                try:
                    await self._validate(probe)
                    if state is not None and is_full(state.occupancy, a.bus.capacity):
                        code, reason = "bus_full", f"Bus {a.bus.id} is full — no seats are available."
                except BoardingRejected as exc:
                    code, reason = exc.code, exc.message
        return StudentBoarding(
            assignment=a,
            trip_id=trip_id,
            ready=boarded is None and code is None,
            reason_code=code,
            reason=reason,
            boarded=boarded,
            occupancy=occupancy_of(a.bus, state),
        )

    async def trip_boarding(self, trip_id: str, principal: Principal) -> TripBoarding:
        """Admins see every event; a student only their own; others the count only."""
        trip = await self._repos.trips.get(trip_id)
        if trip is None:
            raise BoardingRejected("trip_not_found", f"Trip {trip_id} does not exist.", 404)
        events = await self._repos.boarding_events.for_trip(trip_id)
        if principal.role is Role.ADMIN:
            return TripBoarding(trip, len(events), events, "all")
        if principal.role is Role.STUDENT:
            own = [e for e in events if e.student_id == principal.user_id]
            return TripBoarding(trip, len(events), own, "own")
        return TripBoarding(trip, len(events), [], "count_only")
