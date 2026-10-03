from __future__ import annotations

from datetime import date

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
