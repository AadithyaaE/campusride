"""WebSocket wire format (Feature 14): one typed envelope for every server → client message.

    {"id": "evt-…", "type": "bus.state.updated", "seq": 42, "ts": "…", "sent_at": "…",
     "scope": "fleet", "data": {…}}

* ``id``   — unique per message (clients drop duplicates).
* ``seq``  — process-wide, strictly increasing (clients may ignore anything older).
* ``ts``   — when the underlying fact happened (simulation time while simulating).
* ``scope``— who the message was addressed to (fleet / admin / student / driver / system).
* ``data`` — the payload: always a backend DTO already used by the REST API (``BusOut``,
  ``AdminFleetBusOut``, ``DriverDashboardOut``, ``AlertOut``…) or one of the small
  payloads below. Nothing in it is computed by the realtime layer.

Client → server messages: ``{"type": "auth", "token": "…"}`` (first message) and
``{"type": "pong"}`` (heartbeat answer). Anything else is ignored.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.models.common import RouteStatus

WsEventType = Literal[
    "hello",
    "ping",
    "bus.state.updated",
    "fleet.bus.updated",
    "driver.state.updated",
    "trip.started",
    "trip.completed",
    "occupancy.updated",
    "eta.updated",
    "route.deviation",
    "alert.created",
    "alert.updated",
    "alert.resolved",
    "alert.read",
    "boarding.updated",
    "admin.overview.updated",
    "sim.reset",
]
Scope = Literal["fleet", "admin", "student", "driver", "user", "system"]

# WebSocket close codes (4000–4999 are application-defined).
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_AUTH_TIMEOUT = 4408
CLOSE_IDLE = 4410
CLOSE_TOO_SLOW = 4429


class WsEnvelope(BaseModel):
    id: str
    type: WsEventType
    seq: int
    ts: datetime
    sent_at: datetime
    scope: Scope
    data: dict[str, Any]


class HelloData(BaseModel):
    user_id: str
    role: str
    bus_id: str | None
    """For drivers: the bus whose private updates this socket receives."""
    heartbeat_s: float
    flush_interval_s: float


class TripEventData(BaseModel):
    trip_id: str
    bus_id: str
    route_id: str | None
    route_direction_id: str


class OccupancyData(BaseModel):
    """Feature 8 values exactly as ``GET /buses`` reports them for this bus."""

    bus_id: str
    trip_id: str | None
    passengers: int
    capacity: int
    available_seats: int | None
    percentage: int | None
    boarded_count: int


class NamedRef(BaseModel):
    id: str
    name: str


class EtaData(BaseModel):
    """Feature 5 ETA of the bus to its NEXT stop (same value as ``/admin/fleet``)."""

    bus_id: str
    trip_id: str | None
    next_stop: NamedRef | None
    eta_minutes: int | None
    status: str | None
    confidence: str | None


class RouteDeviationData(BaseModel):
    """Feature 10 status change of one bus (entering, changing or leaving a deviation)."""

    bus_id: str
    trip_id: str | None
    route_status: RouteStatus | None
    previous_status: RouteStatus | None
    deviation_distance_m: float | None


class BoardingData(BaseModel):
    trip_id: str
    bus_id: str
    stop_id: str
    student_id: str | None
    """Only sent to admins and to the student who boarded."""


class AlertReadData(BaseModel):
    alert_id: str
    read: bool
