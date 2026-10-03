from __future__ import annotations

from app.models.common import Document, GeoPoint


class Campus(Document):
    name: str
    short_name: str
    location: GeoPoint
    timezone: str = "Asia/Kolkata"
