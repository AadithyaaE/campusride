from __future__ import annotations

from pydantic import Field

from app.models.common import BusSource, Document, FleetStatus


class Bus(Document):
    reg_no: str
    capacity: int = Field(gt=0)
    qr_secret: str = Field(repr=False)
    """Signs rotating boarding QR tokens. Never returned by the API."""
    default_route_id: str
    driver_id: str | None = None
    source: BusSource = BusSource.SIM
    """``sim``: driven by the simulator; ``device``: telemetry comes from a real phone."""
    status: FleetStatus = FleetStatus.ACTIVE
