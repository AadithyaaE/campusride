"""DTOs for the multi-bus comparison (``/students/me/bus-options``).

Each option REUSES the Feature 4/5 shape (``ArrivalOut`` = matched bus + backend
ETA) and adds only the comparison fields. The internal comparison cost and its
weights are deliberately not exposed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.api.eta import ArrivalOut
from app.models.api.matching import StopSummaryOut
from app.models.common import Direction

IndicatorOut = Literal["ASSIGNED", "FASTEST", "LEAST_CROWDED", "BEST_ALTERNATIVE"]


class BusOptionOut(ArrivalOut):
    seats_available: int
    crowding: Literal["Low", "Medium", "High", "Unknown"]
    """Bands: Low < 60 % ≤ Medium < 80 % ≤ High."""
    delay_minutes: int
    """Whole minutes behind the timetable (negative = early)."""
    comparable: bool
    """False for stale or broken-down buses — listed, but given no comparison indicator."""
    indicators: list[IndicatorOut]
    trade_off: str | None
    """Plain-language difference to the fastest bus, e.g. "+3 min vs B07 · 22 more seats free"."""


class ExcludedBusOut(BaseModel):
    """A bus on the stop's direction that is no longer a useful option."""

    bus_id: str
    bus_number: str
    reason: Literal["passed_stop", "trip_completed"]


class BusOptionsOut(BaseModel):
    student_id: str
    status: Literal["assigned", "unassigned"]
    boarding_stop: StopSummaryOut | None
    assigned_bus_id: str | None
    route_direction_id: str | None
    direction: Direction | None
    assigned_bus_available: bool
    """True when the assigned bus is one of the options (serving the stop, not passed)."""
    assigned_bus_note: str | None
    """Why the assigned bus is not an option right now (passed, finished, between trips…)."""
    computed_at: datetime | None
    options: list[BusOptionOut]
    """Useful future options in ARRIVAL order (indicators carry the trade-offs, not the order)."""
    excluded: list[ExcludedBusOut]
