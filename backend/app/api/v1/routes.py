from __future__ import annotations

from fastapi import APIRouter

from app.deps import CurrentPrincipal, Repos
from app.models.api.reference import RouteDetailOut, RouteSummaryOut
from app.services.reference import ReferenceService

router = APIRouter(tags=["routes"])


@router.get("/routes", response_model=list[RouteSummaryOut])
async def list_routes(_: CurrentPrincipal, repos: Repos) -> list[RouteSummaryOut]:
    return [RouteSummaryOut.of(r) for r in await ReferenceService(repos).list_routes()]


@router.get("/routes/{route_id}", response_model=RouteDetailOut)
async def get_route(route_id: str, _: CurrentPrincipal, repos: Repos) -> RouteDetailOut:
    route, stops = await ReferenceService(repos).route_with_stops(route_id)
    return RouteDetailOut.of(route, stops)
