from __future__ import annotations

from app.models.common import Document


class Driver(Document):
    user_id: str
    name: str
    phone: str
    license_no: str
