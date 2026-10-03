from __future__ import annotations

from pydantic import AwareDatetime, Field

from app.models.common import DeviationStatus, Document, LineString


class Deviation(Document):
    trip_id: str
    bus_id: str
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    max_off_route_m: float = Field(ge=0)
    path_sample: LineString | None = None
    status: DeviationStatus = DeviationStatus.OPEN
