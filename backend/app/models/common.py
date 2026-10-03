"""Shared model building blocks: GeoJSON geometry, enums, document base."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.geo import LngLat

Lng = Annotated[float, Field(ge=-180, le=180)]
Lat = Annotated[float, Field(ge=-90, le=90)]


class GeoPoint(BaseModel):
    """GeoJSON Point. NOTE: coordinates are ``(lng, lat)``."""

    model_config = ConfigDict(frozen=True)

    type: Literal["Point"] = "Point"
    coordinates: tuple[Lng, Lat]

    @classmethod
    def of(cls, lng: float, lat: float) -> Self:
        return cls(coordinates=(lng, lat))

    @property
    def lng(self) -> float:
        return self.coordinates[0]

    @property
    def lat(self) -> float:
        return self.coordinates[1]

    @property
    def lnglat(self) -> LngLat:
        return self.coordinates


class LineString(BaseModel):
    """GeoJSON LineString of ``(lng, lat)`` positions."""

    type: Literal["LineString"] = "LineString"
    coordinates: list[tuple[Lng, Lat]]

    @field_validator("coordinates")
    @classmethod
    def _min_two(cls, v: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(v) < 2:
            raise ValueError("LineString needs at least 2 positions")
        return v


# --------------------------------------------------------------------------- enums


class Role(StrEnum):
    STUDENT = "student"
    DRIVER = "driver"
    ADMIN = "admin"


class Direction(StrEnum):
    TO_CAMPUS = "to_campus"
    FROM_CAMPUS = "from_campus"


class SegmentClass(StrEnum):
    HIGHWAY = "highway"
    ARTERIAL = "arterial"
    LOCAL = "local"


class BusSource(StrEnum):
    SIM = "sim"
    DEVICE = "device"


class FleetStatus(StrEnum):
    """Administrative status of a bus (not its live driving state)."""

    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"


class TripStatus(StrEnum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StopProximity(StrEnum):
    """Where a bus is relative to ONE stop on its current route direction.

    Orthogonal to ``BusStatus`` (which describes motion: en_route, dwelling, …).
    """

    FAR_FROM_STOP = "far_from_stop"
    APPROACHING_STOP = "approaching_stop"
    AT_STOP = "at_stop"
    PASSED_STOP = "passed_stop"


class BusStatus(StrEnum):
    """Live driving state of a bus, derived by tracking from telemetry."""

    SCHEDULED = "scheduled"
    AT_DEPOT = "at_depot"
    EN_ROUTE = "en_route"
    DWELLING = "dwelling"
    DEVIATED = "deviated"
    BREAKDOWN = "breakdown"
    COMPLETED = "completed"


class RouteStatus(StrEnum):
    """Feature 10: a bus relative to its PLANNED route geometry (see route_anomaly_service)."""

    NORMAL = "NORMAL"
    MINOR_DEVIATION = "MINOR_DEVIATION"
    MAJOR_DEVIATION = "MAJOR_DEVIATION"
    NO_ACTIVE_TRIP = "NO_ACTIVE_TRIP"
    NO_ROUTE = "NO_ROUTE"
    NO_LIVE_DATA = "NO_LIVE_DATA"
    STALE = "STALE"
    INVALID_LOCATION = "INVALID_LOCATION"


class BoardingType(StrEnum):
    BOARD = "board"
    ALIGHT = "alight"


class BoardingSource(StrEnum):
    QR = "qr"
    SIM = "sim"


class DeviationStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class AlertType(StrEnum):
    DELAY = "delay"
    DEVIATION = "deviation"
    BREAKDOWN = "breakdown"
    CAPACITY_FULL = "capacity_full"
    BUS_APPROACHING = "bus_approaching"
    MISSED_BUS = "missed_bus"
    BROADCAST = "broadcast"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# --------------------------------------------------------------------------- document base


def _bsonify(value: Any) -> Any:
    """Make a ``model_dump(mode="python")`` result BSON-encodable.

    BSON has no plain ``date`` type, so dates are stored as ISO strings
    (``2026-10-05``); pydantic parses them back on load.
    """
    if isinstance(value, dict):
        return {k: _bsonify(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_bsonify(v) for v in value]
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    return value


class Document(BaseModel):
    """Base for MongoDB documents: ``id`` in Python ↔ ``_id`` in Mongo."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(alias="_id")

    def to_mongo(self) -> dict[str, Any]:
        return _bsonify(self.model_dump(by_alias=True, mode="python"))

    @classmethod
    def from_mongo(cls, raw: dict[str, Any]) -> Self:
        return cls.model_validate(raw)
