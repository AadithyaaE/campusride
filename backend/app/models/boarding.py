from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime

from app.models.common import BoardingSource, BoardingType, Document


class BoardingEvent(Document):
    """One boarding. QR boardings use ``id = BRD-<trip_id>-<student_id>`` (server-derived)
    and a unique ``(student_id, trip_id)`` index: a student boards a trip at most once."""

    trip_id: str
    bus_id: str
    stop_id: str
    student_id: str | None = None
    ts: AwareDatetime
    type: BoardingType
    source: BoardingSource
    qr_ts: AwareDatetime | None = None
    """Timestamp carried in the QR payload (synthetic in the prototype); ``ts`` is server time."""
    scanner: Literal["simulated", "camera"] | None = None
    """Which scanner produced the QR (informational; the endpoint is the same)."""
