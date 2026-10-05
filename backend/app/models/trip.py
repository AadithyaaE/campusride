from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AwareDatetime

from app.models.common import Direction, Document, TripStatus


class Trip(Document):
    """One scheduled run of a route variant by a bus, e.g. ``T-20261005-R1-0715``."""

    route_id: str
    """Physical route (``R1``)."""
    direction: Direction
    variant_id: str
    """Route + direction (``R1`` / ``R1-E``)."""
    bus_id: str
    driver_id: str | None = None
    service_date: date
    """Campus-local service date."""
    scheduled_start: AwareDatetime
    actual_start: AwareDatetime | None = None
    actual_end: AwareDatetime | None = None
    status: TripStatus = TripStatus.SCHEDULED
    end_reason: Literal["terminal", "driver_stop"] | None = None
    """Feature 16: how a COMPLETED trip ended — reached its last stop (tracking) or was
    stopped by the driver (Feature 12 Stop Trip, possibly before every stop was served)."""
