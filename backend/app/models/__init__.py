"""Pydantic models.

* Domain documents (one per MongoDB collection) live in this package.
* Domain events live in ``app.models.events``.
* API request/response DTOs live in ``app.models.api`` — routers never
  return domain documents directly (e.g. ``Bus.qr_secret`` must not leak).
"""

from app.models.alert import Alert, AlertAudience
from app.models.assignment import StudentAssignment
from app.models.boarding import BoardingEvent
from app.models.bus import Bus
from app.models.bus_state import BusState
from app.models.campus import Campus
from app.models.common import Document, GeoPoint, LineString
from app.models.deviation import Deviation
from app.models.driver import Driver
from app.models.route import Route, RouteDirection, RouteStop
from app.models.stop import Stop
from app.models.student import NotificationPrefs, StudentProfile
from app.models.telemetry import Telemetry, TelemetryMeta
from app.models.traffic import TrafficIncident, TrafficProfile
from app.models.trip import Trip
from app.models.user import User

__all__ = [
    "Alert",
    "AlertAudience",
    "BoardingEvent",
    "Bus",
    "BusState",
    "Campus",
    "Deviation",
    "Document",
    "Driver",
    "GeoPoint",
    "LineString",
    "NotificationPrefs",
    "Route",
    "RouteDirection",
    "RouteStop",
    "Stop",
    "StudentAssignment",
    "StudentProfile",
    "Telemetry",
    "TelemetryMeta",
    "TrafficIncident",
    "TrafficProfile",
    "Trip",
    "User",
]
