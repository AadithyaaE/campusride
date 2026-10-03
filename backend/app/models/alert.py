from __future__ import annotations

from typing import Any

from pydantic import AwareDatetime, BaseModel, Field

from app.models.common import AlertType, Document, Role, Severity


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
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime
    acked_by: list[str] = Field(default_factory=list)
