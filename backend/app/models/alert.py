"""In-app alerts (Feature 10 introduced the model; Feature 11 centralises it).

One ``Alert`` document per notification episode. Recipients reuse ``AlertAudience``:
a student alert has ``audience.user_id = <student id>``; a fleet/admin alert has
``audience.role = admin`` (visible to every admin, read flag shared).

Deduplication: ``dedup_key`` names the alert SERIES (type + recipient + bus + trip);
``id`` = series + episode number. At most one ACTIVE alert per series (unique
partial index on ``dedup_key`` where ``active``); see ``services/alert_service.py``.
"""

from __future__ import annotations

from typing import Any

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from app.models.common import AlertType, Document, Role, Severity

_LEGACY_TYPES = {
    "deviation": AlertType.ROUTE_DEVIATION,
    "delay": AlertType.BUS_DELAYED,
    "capacity_full": AlertType.CAPACITY_WARNING,
    "bus_approaching": AlertType.BUS_APPROACHING,
    "missed_bus": AlertType.MISSED_BUS,
}


class AlertAudience(BaseModel):
    """Who should see an alert. Unset fields do not restrict the audience."""

    role: Role | None = None
    route_id: str | None = None
    stop_id: str | None = None
    user_id: str | None = None


class Alert(Document):
    type: AlertType
    severity: Severity
    audience: AlertAudience = Field(default_factory=AlertAudience)
    title: str
    body: str
    """The message shown to the user (observed facts only)."""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime
    acked_by: list[str] = Field(default_factory=list)
    """Users who marked the alert read (for shared admin alerts)."""
    resolved_at: AwareDatetime | None = None
    """When the observed condition ended (e.g. the bus returned to its route)."""
    # --- Feature 11 ---
    bus_id: str | None = None
    trip_id: str | None = None
    route_id: str | None = None
    dedup_key: str | None = None
    """Series key: ``TYPE|recipient|bus|trip``. One active alert per series."""
    episode: int = 1
    active: bool = True
    """False once resolved (kept in sync with ``resolved_at`` for the partial unique index)."""
    read: bool = False
    read_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    """Set when an active alert's message is refreshed in place (no new alert)."""

    @field_validator("type", mode="before")
    @classmethod
    def _legacy_type(cls, v: object) -> object:
        """Feature 10 stored lowercase types (e.g. ``deviation``) — read them as the new enum."""
        return _LEGACY_TYPES.get(v, v) if isinstance(v, str) else v

    @property
    def student_id(self) -> str | None:
        return self.audience.user_id if self.audience.role is not Role.ADMIN else None
