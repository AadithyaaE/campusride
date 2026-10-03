"""Telemetry as SENT by a driver phone — or by the simulator acting as one.

Body of ``POST /api/v1/driver/telemetry`` and the input of
``TelemetryIngestService.ingest`` (the single ingestion path).
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, Field

from app.models.common import Lat, Lng


class TelemetryPointIn(BaseModel):
    ts: AwareDatetime
    lng: Lng
    lat: Lat
    speed_mps: float | None = Field(default=None, ge=0, le=60)
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    accuracy_m: float = Field(default=10.0, ge=0)
    occupancy: int | None = Field(default=None, ge=0)
    """Optional headcount reported by the driver. SYNTHETIC in the simulator;
    replaced by QR boarding counts in Phase 5."""


class TelemetryBatchIn(BaseModel):
    bus_id: str
    trip_id: str | None = None
    points: list[TelemetryPointIn] = Field(min_length=1, max_length=100)
