"""DTOs for missed-bus recovery (``/students/me/recovery-options``, Feature 9).

Recovery suggestions do not change the student's college-assigned bus.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.api.eta import EtaPredictionOut
from app.models.common import BusStatus, Direction
from app.services.missed_bus_service import RecoveryOption


class RecoveryOptionOut(BaseModel):
    bus_id: str
    bus_number: str
    trip_id: str | None
    route_id: str
    route_direction_id: str
    route_name: str
    direction: Direction
    boarding_stop_id: str
    boarding_stop_name: str
    eta_minutes: int | None
    estimated_arrival_time: datetime | None
    eta: EtaPredictionOut
    """Feature 5 prediction (the countdown's source of truth)."""
    occupancy: int
    capacity: int
    available_seats: int
    occupancy_percentage: int | None
    status: Literal["on_time", "delayed"]
    bus_status: BusStatus
    delay_minutes: int
    distance_to_stop_m: int | None
    stops_away: int | None
    catchable: bool | None
    """True: Feature 7 rules say YES for this bus; null: unknown (no student location)."""
    safety_buffer_minutes: int | None
    """Whole minutes the student would wait at the stop before this bus arrives."""
    walking_time_minutes: int | None
    reason: str

    @classmethod
    def of(cls, o: RecoveryOption, stop_id: str, stop_name: str) -> RecoveryOptionOut:
        c = o.candidate
        sb, p = c.option.sb, c.option.prediction
        m = sb.match
        return cls(
            bus_id=sb.bus.id,
            bus_number=sb.bus.id,
            trip_id=sb.state.trip_id,
            route_id=sb.route.id,
            route_direction_id=sb.position.direction.variant_id,
            route_name=sb.route.name,
            direction=sb.position.direction.direction,
            boarding_stop_id=stop_id,
            boarding_stop_name=stop_name,
            eta_minutes=p.eta_minutes,
            estimated_arrival_time=p.estimated_arrival,
            eta=EtaPredictionOut.of(p),
            occupancy=sb.state.occupancy,
            capacity=sb.bus.capacity,
            available_seats=o.available_seats,
            occupancy_percentage=o.occupancy_percentage,
            status="delayed" if c.delayed else "on_time",
            bus_status=sb.state.status,
            delay_minutes=round(sb.state.delay_s / 60),
            distance_to_stop_m=(
                None if m is None or m.distance_to_stop_m is None else round(m.distance_to_stop_m)
            ),
            stops_away=None if m is None else m.stops_away,
            catchable=c.catchable,
            safety_buffer_minutes=c.spare_minutes if c.catchable else None,
            walking_time_minutes=c.catch.walking_time_minutes,
            reason=o.reason,
        )


class ExcludedRecoveryBusOut(BaseModel):
    bus_id: str
    reason: Literal[
        "at_stop_now",
        "stale",
        "breakdown",
        "off_route",
        "full",
        "too_late",
        "passed_stop",
        "trip_completed",
    ]


class RecoveryOut(BaseModel):
    student_id: str
    status: Literal["recovery_available", "not_needed", "no_alternative", "unassigned"]
    trigger: Literal["missed", "likely_to_miss", "significantly_delayed"] | None
    commute_decision: Literal["YES", "RISK", "MISSED", "LOCATION_UNAVAILABLE", "UNKNOWN"] | None
    """Feature 7's decision for the ASSIGNED bus — reported, never changed by recovery."""
    assigned_bus_id: str | None
    assigned_bus: str | None
    """Display label, e.g. "BUS B05"."""
    assigned_bus_delay_minutes: int | None
    boarding_stop_id: str | None
    boarding_stop_name: str | None
    route_direction_id: str | None
    required_buffer_minutes: int
    """Feature 7 safety buffer every recommended bus must leave."""
    recommended: RecoveryOptionOut | None
    alternatives: list[RecoveryOptionOut]
    """At most ``RECOVERY_MAX_ALTERNATIVES``, in the documented ranking order."""
    excluded: list[ExcludedRecoveryBusOut]
    """Buses serving the stop that can't be offered, and why."""
    computed_at: datetime
