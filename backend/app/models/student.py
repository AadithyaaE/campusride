from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.common import Document


class NotificationPrefs(BaseModel):
    bus_approaching: bool = True
    approach_lead_min: int = Field(default=5, ge=1, le=30)
    delays: bool = True
    deviations: bool = False
    capacity: bool = True


class StudentProfile(Document):
    """``id`` is the student's user id (one profile per user)."""

    roll_no: str
    home_stop_id: str
    preferred_route_ids: list[str] = Field(default_factory=list)
    """Physical route ids (``R1``) serving the home stop."""
    walk_speed_mps: float = Field(default=1.3, ge=0.5, le=3.0)
    notification_prefs: NotificationPrefs = Field(default_factory=NotificationPrefs)
