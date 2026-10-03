from __future__ import annotations

from pydantic import Field

from app.models.common import Document, GeoPoint


class Stop(Document):
    name: str
    location: GeoPoint
    campus_id: str
    walk_radius_m: float = Field(default=400, gt=0)
    is_campus_terminal: bool = False
