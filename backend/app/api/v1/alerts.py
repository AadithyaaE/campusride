"""Alerts (admin). Feature 10 adds the first producer: MAJOR route deviation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.auth import Principal
from app.deps import Container, require_role
from app.models.api.route_status import AlertOut
from app.models.common import Role

router = APIRouter(tags=["alerts"])

Admin = Annotated[Principal, Depends(require_role(Role.ADMIN))]


@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    _: Admin,
    c: Container,
    active: bool = Query(False, description="Only alerts whose condition is still ongoing"),
    limit: int = Query(50, ge=1, le=500),
) -> list[AlertOut]:
    """Most recent alerts first (created from backend state transitions, never from polling)."""
    alerts = await c.repos.alerts.recent(limit=limit if not active else 500)
    if active:
        alerts = [a for a in alerts if a.resolved_at is None][:limit]
    return [AlertOut.of(a) for a in alerts]
