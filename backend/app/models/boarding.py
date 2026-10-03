from __future__ import annotations

from pydantic import AwareDatetime

from app.models.common import BoardingSource, BoardingType, Document


class BoardingEvent(Document):
    trip_id: str
    bus_id: str
    stop_id: str
    student_id: str | None = None
    ts: AwareDatetime
    type: BoardingType
    source: BoardingSource
