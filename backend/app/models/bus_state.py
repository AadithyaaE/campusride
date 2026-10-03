from __future__ import annotations

from pydantic import AwareDatetime, Field

from app.models.common import BusStatus, Direction, Document, GeoPoint, RouteStatus


class BusState(Document):
    """Latest derived state of one bus (``id`` = bus id). One document per bus.

    Written only by the tracking service from telemetry; read by ETA,
    comparison, decision, recovery, deviation and the realtime layer.
    """

    trip_id: str | None = None
    route_id: str | None = None
    variant_id: str | None = None
    direction: Direction | None = None
    ts: AwareDatetime
    """Timestamp of the telemetry this state was derived from."""
    last_seen: AwareDatetime
    location: GeoPoint
    distance_along_m: float = Field(default=0.0, ge=0)
    """Position along the current variant's polyline (direction-specific frame)."""
    off_route_m: float = Field(default=0.0, ge=0)
    speed_mps: float = Field(default=0.0, ge=0)
    heading_deg: float | None = None
    next_stop_seq: int | None = None
    current_stop_id: str | None = None
    """Stop the bus is at, or the last stop it departed while moving."""
    next_stop_id: str | None = None
    route_progress: float = Field(default=0.0, ge=0, le=1)
    """distance_along_m / route length, 0..1."""
    delay_s: int = 0
    """Seconds behind (+) or ahead of (−) the timetable at the current position."""
    occupancy: int = Field(default=0, ge=0)
    """Live occupancy = min(capacity, baseline + boarded) — see ``services/capacity.py``."""
    occupancy_baseline: int = Field(default=0, ge=0)
    """Driver-reported headcount from telemetry (SYNTHETIC for simulated buses)."""
    boarded_count: int = Field(default=0, ge=0)
    """QR boarding events recorded for the current trip (counted, never incremented)."""
    status: BusStatus = BusStatus.SCHEDULED
    route_status: RouteStatus | None = None
    """Feature 10: position vs. the planned route at this fix (set by the ingest service)."""
    deviation_m: float | None = None
    """Shortest distance from ``location`` to the planned route geometry (m)."""
    stale: bool = False
    """True when no telemetry has arrived for BUS_STALE_AFTER_S (e.g. GPS dropout)."""
    last_stop_departures: dict[str, AwareDatetime] = Field(default_factory=dict)
    """stop_id → departure time on the current trip."""
