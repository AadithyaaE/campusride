"""DTOs for the student commute experience (Feature 16): ``/students/me/commute`` and
``/students/me/history``. Nested blocks reuse the existing DTOs unchanged."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.api.v1.buses import BusOut
from app.models.api.boarding import MyBoardingOut
from app.models.api.commute import CommuteDecisionOut
from app.models.api.matching import StopSummaryOut
from app.models.api.recovery import RecoveryOut
from app.models.api.route_status import AlertOut
from app.models.api.students import AssignmentOut
from app.models.common import BoardingSource, Direction, TripStatus
from app.services.student_commute_service import Outcome, Phase


class CommuteTripOut(BaseModel):
    trip_id: str
    status: TripStatus
    route_direction_id: str
    direction: Direction
    scheduled_start: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    end_reason: Literal["terminal", "driver_stop"] | None


class StudentCommuteOut(BaseModel):
    """Everything "Today's Commute" shows, decided by the backend, for the signed-in student."""

    student_id: str
    status: Literal["assigned", "unassigned"]
    phase: Phase
    """Backend commute phase: unassigned / no_trip / waiting / approaching / at_stop /
    on_board / completed / missed / recovery_available."""
    phase_reason: str
    assignment: AssignmentOut | None
    bus: BusOut | None
    """The assigned bus as ``GET /buses`` reports it (location, status, occupancy…)."""
    trip: CommuteTripOut | None
    """The assigned bus's current trip (stored record)."""
    decision: CommuteDecisionOut
    """Feature 7 "Will I make my bus?" (incl. the Feature 5 ETA)."""
    recovery: RecoveryOut
    """Feature 9 missed-bus recovery."""
    boarding: MyBoardingOut
    """Feature 8 boarding state for the current trip."""
    alerts: list[AlertOut]
    """The student's own ACTIVE alerts (Feature 11)."""
    computed_at: datetime


class CommuteHistoryEntryOut(BaseModel):
    trip_id: str
    service_date: date
    bus_id: str
    route_id: str
    route_name: str | None
    route_direction_id: str
    direction: Direction
    direction_label: str | None
    boarding_stop: StopSummaryOut | None
    scheduled_departure: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    trip_status: TripStatus
    end_reason: Literal["terminal", "driver_stop"] | None
    outcome: Outcome
    """boarded · in_progress · missed (a Feature 11 MISSED_BUS alert exists) · ended_early (the
    driver stopped the trip before your stop) · no_boarding_recorded · cancelled."""
    boarded: bool
    boarding_time: datetime | None
    boarding_source: BoardingSource | None
    scanner: Literal["simulated", "camera"] | None
    """``simulated``: the prototype's simulated QR scanner (still a real backend boarding)."""


class CommuteHistoryOut(BaseModel):
    student_id: str
    entries: list[CommuteHistoryEntryOut]
    generated_at: datetime
