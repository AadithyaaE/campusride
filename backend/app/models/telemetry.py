from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models.common import BusSource, GeoPoint


class TelemetryMeta(BaseModel):
    """Time-series ``metaField``: what the reading belongs to."""

    bus_id: str
    trip_id: str | None = None
    source: BusSource


class Telemetry(BaseModel):
    """One GPS reading — exactly what a phone (or the simulator acting as one) can report.

    Stored in a MongoDB time-series collection with a TTL (default 30 days).
    """

    model_config = ConfigDict(extra="ignore")  # time-series documents carry a generated _id

    ts: AwareDatetime
    meta: TelemetryMeta
    location: GeoPoint
    speed_mps: float | None = Field(default=None, ge=0)
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    accuracy_m: float = Field(ge=0)
