"""DTOs for backend ETA (``/buses/{id}/eta``) and arrivals (stop / student arrivals)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.api.matching import StopBusOut, StopSummaryOut
from app.models.common import Direction, StopProximity
from app.services.eta_service import EtaPrediction


class EtaBreakdownOut(BaseModel):
    """Components in seconds (for transparency/debugging; the UI shows ``eta_minutes``)."""

    travel_s: float
    dwell_s: float
    wait_s: float
    timetable_s: float | None
    history_source: Literal["timetable"] | None
    """Prototype "historical average" = the published synthetic timetable, not observed trips."""


class EtaPredictionOut(BaseModel):
    status: Literal["predicted", "at_stop", "passed", "completed"]
    eta_minutes: int | None
    """Whole minutes for display; 0 means "<1 min" (or at the stop). Null when passed/completed."""
    eta_seconds: int | None
    estimated_arrival_time: datetime | None
    computed_at: datetime
    """Simulation time the prediction was made — the countdown's reference point."""
    confidence: Literal["high", "medium", "low"]
    traffic: Literal["Low", "Moderate", "High"]
    traffic_factor: float
    delay_factor: float
    breakdown: EtaBreakdownOut

    @classmethod
    def of(cls, p: EtaPrediction) -> EtaPredictionOut:
        return cls(
            status=p.status,
            eta_minutes=p.eta_minutes,
            eta_seconds=None if p.eta_s is None else round(p.eta_s),
            estimated_arrival_time=p.estimated_arrival,
            computed_at=p.computed_at,
            confidence=p.confidence,
            traffic=p.traffic_level,
            traffic_factor=round(p.traffic_factor, 2),
            delay_factor=round(p.delay_factor, 2),
            breakdown=EtaBreakdownOut(
                travel_s=p.travel_s,
                dwell_s=p.dwell_s,
                wait_s=p.wait_s,
                timetable_s=p.timetable_s,
                history_source=p.history_source,
            ),
        )


class BusEtaOut(EtaPredictionOut):
    bus_id: str
    bus_number: str
    reg_no: str
    stop_id: str
    stop_name: str
    route_id: str
    route_direction_id: str
    direction: Direction
    proximity: StopProximity
    distance_to_stop_m: float | None
    stops_away: int | None
    delay_s: int


class ArrivalOut(StopBusOut):
    """A bus serving the stop (Feature 4 matching) + its backend ETA."""

    eta: EtaPredictionOut


class StopArrivalsOut(BaseModel):
    stop: StopSummaryOut
    arrivals: list[ArrivalOut]
    """Ordered: at the stop, then by predicted ETA, then completed / passed."""


class MyArrivalsOut(BaseModel):
    student_id: str
    status: Literal["assigned", "unassigned"]
    boarding_stop: StopSummaryOut | None
    assigned_bus_id: str | None
    route_direction_id: str | None
    direction: Direction | None
    my_bus: ArrivalOut | StopBusOut | None
    """The assigned bus: with ``eta`` when it serves the stop now, else its position only."""
    my_bus_serving_stop: bool
    arrivals: list[ArrivalOut]
    """All buses serving the boarding stop in the assigned direction (incl. mine), by ETA."""
