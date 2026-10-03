"""DTOs for QR boarding and live occupancy (Feature 8)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from app.models import BoardingEvent
from app.models.api.matching import StopSummaryOut
from app.services.boarding_service import Occupancy


class QrPayloadIn(BaseModel):
    """What a boarding QR carries. PROTOTYPE: unsigned JSON from a simulated scanner."""

    student_id: str = Field(min_length=1)
    bus_id: str = Field(min_length=1)
    trip_id: str = Field(min_length=1)
    timestamp: AwareDatetime
    """Synthetic/demo time from the QR; the server records its own time."""


class BoardingScanIn(QrPayloadIn):
    stop_id: str | None = None
    """Optional; must equal the ASSIGNED boarding stop. The server never trusts it otherwise."""
    scanner: Literal["simulated", "camera"] = "simulated"


class OccupancyOut(BaseModel):
    bus_id: str
    trip_id: str | None
    """The bus's running trip (null between trips / when completed)."""
    occupancy: int
    capacity: int
    available_seats: int
    occupancy_percentage: int | None
    baseline: int
    """Synthetic driver-reported headcount (0 for device buses)."""
    boarded: int
    """QR boardings recorded for the current trip."""
    source: Literal["synthetic_baseline+qr", "qr", "no_live_data"]
    updated_at: datetime | None

    @classmethod
    def of(cls, o: Occupancy) -> OccupancyOut:
        return cls(
            bus_id=o.bus_id,
            trip_id=o.trip_id,
            occupancy=o.occupancy,
            capacity=o.capacity,
            available_seats=o.available_seats,
            occupancy_percentage=o.occupancy_percentage,
            baseline=o.baseline,
            boarded=o.boarded,
            source=o.source,
            updated_at=o.updated_at,
        )


class BoardingEventOut(BaseModel):
    boarding_id: str
    student_id: str | None
    bus_id: str
    trip_id: str
    stop_id: str
    timestamp: datetime
    """Server (simulation) time the boarding was recorded."""
    scanner: Literal["simulated", "camera"] | None

    @classmethod
    def of(cls, e: BoardingEvent) -> BoardingEventOut:
        return cls(
            boarding_id=e.id,
            student_id=e.student_id,
            bus_id=e.bus_id,
            trip_id=e.trip_id,
            stop_id=e.stop_id,
            timestamp=e.ts,
            scanner=e.scanner,
        )


class BoardingScanOut(OccupancyOut):
    status: Literal["boarded", "already_boarded"]
    boarding_id: str
    student_id: str
    stop_id: str
    timestamp: datetime
    message: str


class TripBoardingOut(BaseModel):
    trip_id: str
    bus_id: str
    route_direction_id: str
    total_boarded: int
    visibility: Literal["all", "own", "count_only"]
    """Admins see every event; a student only their own; others the count only."""
    events: list[BoardingEventOut]


class MyBoardingOut(BaseModel):
    """Scanner screen state for the signed-in student (assignment-derived, read-only)."""

    student_id: str
    status: Literal["assigned", "unassigned"]
    bus_id: str | None
    bus_number: str | None
    route_direction_id: str | None
    boarding_stop: StopSummaryOut | None
    trip_id: str | None
    """The assigned bus's current trip — what the simulated QR will carry."""
    ready: bool
    """True when a scan would be accepted now."""
    reason_code: str | None
    reason: str | None
    boarded: BoardingEventOut | None
    occupancy: OccupancyOut | None
