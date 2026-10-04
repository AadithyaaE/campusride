"""In-app alerts (Feature 11): a student's own alerts, or the admins' fleet alerts.

Alerts are created by the backend ``AlertService`` from state transitions — never by
these endpoints. Feature 11 uses HTTP polling for the prototype; the same alert events
(``AlertCreated``/``Updated``/``Resolved``/``Read``) can later be pushed over WebSockets.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.errors import ForbiddenError
from app.deps import Container, CurrentPrincipal
from app.models.api.route_status import AlertOut
from app.models.common import Role

router = APIRouter(tags=["alerts"])


def _check_role(role: Role) -> None:
    if role not in (Role.STUDENT, Role.ADMIN):
        raise ForbiddenError("in-app alerts are for students and admins")


@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    principal: CurrentPrincipal,
    c: Container,
    active: bool | None = Query(None, description="true: ongoing only · false: resolved only"),
    unread: bool | None = Query(None, description="true: unread only · false: read only"),
    limit: int = Query(50, ge=1, le=500),
) -> list[AlertOut]:
    """Newest first. Students: only their own alerts. Admins: fleet/operational alerts."""
    _check_role(principal.role)
    alerts = await c.alerts().list_for(principal, active=active, unread=unread, limit=limit)
    return [AlertOut.of(a) for a in alerts]


@router.patch("/alerts/{alert_id}/read", response_model=AlertOut)
async def mark_alert_read(alert_id: str, principal: CurrentPrincipal, c: Container) -> AlertOut:
    """Mark one alert read (idempotent). Alerts that aren't yours → 404 (nothing leaks)."""
    _check_role(principal.role)
    return AlertOut.of(await c.alerts().mark_read(principal, alert_id))
