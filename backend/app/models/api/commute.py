"""DTO for the commute decision (``/students/me/commute-decision``, Feature 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models import GeoPoint
from app.models.api.eta import EtaPredictionOut
from app.models.api.matching import StopSummaryOut
from app.models.common import BusStatus, StopProximity


class StudentLocationOut(BaseModel):
    location: GeoPoint
    source: Literal["synthetic"]
    """Always ``synthetic`` in the prototype — a demo location, never real GPS."""
    label: str


class CommuteDecisionOut(BaseModel):
    student_id: str
    status: Literal["assigned", "unassigned"]
    decision: Literal["YES", "RISK", "MISSED", "LOCATION_UNAVAILABLE", "UNKNOWN"] | None
    """YES / RISK / MISSED are decisions; LOCATION_UNAVAILABLE / UNKNOWN mean none can be made."""
    reason: str | None
    bus_id: str | None
    bus_number: str | None
    route_direction_id: str | None
    boarding_stop: StopSummaryOut | None
    student_location: StudentLocationOut | None
    walking_distance_m: int | None
    """Estimated walk (straight line × street detour factor), metres."""
    walking_speed_mps: float | None
    walking_time_minutes: int | None
    """Whole minutes rounded up; 0 = under a minute."""
    bus_eta_minutes: int | None
    bus_arrival_time: datetime | None
    """Feature 5 estimated arrival (sim time, UTC) — the countdown's source of truth."""
    required_arrival_time: datetime | None
    """``bus_arrival_time − safety buffer``: be at the stop before then for a YES."""
    student_arrival_time: datetime | None
    safety_buffer_minutes: int
    spare_minutes: int | None
    """Whole minutes between reaching the stop and the bus arriving (negative = bus first)."""
    delay_minutes: int | None
    """Explanation only — already inside the ETA, never added again."""
    bus_status: BusStatus | None
    proximity: StopProximity | None
    stale: bool
    eta: EtaPredictionOut | None
    """The assigned bus's Feature 5 prediction (for the countdown); null if not serving."""
    alternatives_available: int
    """Other buses serving the stop now (see bus options) — the decision never switches to them."""
    computed_at: datetime
