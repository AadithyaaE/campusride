"""Transport admin dashboard (Feature 13). Admins only — students and drivers get 403.

Read-only aggregates over the existing backend state; route and schedule management are
read-only for now (no mutation APIs exist). Polled over HTTP by the admin web app.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.auth import Principal
from app.deps import Container, require_role
from app.models.api.admin import (
    AdminAnalyticsOut,
    AdminFleetOut,
    AdminOverviewOut,
    AdminRouteOut,
    AdminScheduleOut,
    OperationalStatus,
)
from app.models.common import Role

router = APIRouter(prefix="/admin", tags=["admin"])

Admin = Annotated[Principal, Depends(require_role(Role.ADMIN))]


@router.get("/overview", response_model=AdminOverviewOut)
async def overview(_: Admin, c: Container) -> AdminOverviewOut:
    """KPIs: buses, trips, students, passengers today, delays, deviations, alert counts."""
    return await c.admin().overview()


@router.get("/fleet", response_model=AdminFleetOut)
async def fleet(
    _: Admin,
    c: Container,
    route_id: str | None = Query(None, description="Assigned route, e.g. R1"),
    bus_id: str | None = Query(None, description="One bus, e.g. B07"),
    status: Annotated[OperationalStatus | None, Query(description="Operational status")] = None,
) -> AdminFleetOut:
    """Every bus with position, speed, stops, ETA, delay, occupancy, route status and alerts."""
    return await c.admin().fleet(route_id=route_id, bus_id=bus_id, status=status)


@router.get("/routes", response_model=list[AdminRouteOut])
async def routes(_: Admin, c: Container) -> list[AdminRouteOut]:
    """Routes with directions, stops summary and today's operational aggregates (read-only)."""
    return await c.admin().routes()


@router.get("/schedule", response_model=AdminScheduleOut)
async def schedule(
    _: Admin, c: Container, route_id: str | None = Query(None, description="Only this route")
) -> AdminScheduleOut:
    """Today's trips: departure, arrival, assigned bus and driver, status (read-only)."""
    return await c.admin().schedule(route_id=route_id)


@router.get("/analytics", response_model=AdminAnalyticsOut)
async def analytics(_: Admin, c: Container) -> AdminAnalyticsOut:
    """Live aggregates of today + a separate, labelled block of synthetic demo history."""
    return await c.admin().analytics()
