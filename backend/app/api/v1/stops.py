from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.deps import Container, CurrentPrincipal, Repos
from app.models.api.eta import ArrivalOut, EtaPredictionOut, StopArrivalsOut
from app.models.api.matching import StopBusesOut, StopBusOut, StopSummaryOut
from app.models.api.reference import NearbyStopOut, StopOut, StopServiceOut
from app.models.common import Direction
from app.services.reference import ReferenceService

router = APIRouter(tags=["stops"])


@router.get("/stops", response_model=list[StopOut])
async def list_stops(_: CurrentPrincipal, repos: Repos) -> list[StopOut]:
    return [StopOut.of(s) for s in await ReferenceService(repos).list_stops()]


# Declared before /stops/{stop_id} so "nearby" is not captured as an id.
@router.get("/stops/nearby", response_model=list[NearbyStopOut])
async def nearby_stops(
    _: CurrentPrincipal,
    repos: Repos,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    radius_m: Annotated[float, Query(gt=0, le=5_000)] = 1_000,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[NearbyStopOut]:
    hits = await ReferenceService(repos).nearby_stops(lng, lat, radius_m, limit)
    return [NearbyStopOut(**StopOut.of(s).model_dump(), distance_m=round(d, 1)) for s, d in hits]


@router.get("/stops/{stop_id}", response_model=StopOut)
async def get_stop(stop_id: str, _: CurrentPrincipal, repos: Repos) -> StopOut:
    return StopOut.of(await ReferenceService(repos).get_stop(stop_id))


@router.get("/stops/{stop_id}/routes", response_model=list[StopServiceOut])
async def stop_routes(stop_id: str, _: CurrentPrincipal, repos: Repos) -> list[StopServiceOut]:
    return [StopServiceOut.of(s) for s in await ReferenceService(repos).services_at_stop(stop_id)]


@router.get("/stops/{stop_id}/buses", response_model=StopBusesOut)
async def stop_buses(
    stop_id: str,
    _: CurrentPrincipal,
    c: Container,
    direction: Direction | None = None,
) -> StopBusesOut:
    """Buses whose CURRENT route direction serves the stop, with their position relative to it."""
    serving = await c.matching().buses_serving_stop(stop_id, direction=direction)
    stop = await c.repos.stops.get(stop_id)
    assert stop is not None  # buses_serving_stop raised NotFound otherwise
    names = await c.matching().stop_names(serving)
    return StopBusesOut(
        stop=StopSummaryOut(id=stop.id, name=stop.name),
        buses=[StopBusOut.of(sb, names, c.clock, c.settings.bus_stale_after_s) for sb in serving],
    )


@router.get("/stops/{stop_id}/arrivals", response_model=StopArrivalsOut)
async def stop_arrivals(
    stop_id: str,
    _: CurrentPrincipal,
    c: Container,
    direction: Direction | None = None,
) -> StopArrivalsOut:
    """Buses serving the stop (Feature 4 matching) with backend ETAs, ordered by ETA."""
    items = await c.eta().stop_arrivals(stop_id, direction=direction)
    stop = await c.repos.stops.get(stop_id)
    assert stop is not None
    names = await c.matching().stop_names([sb for sb, _ in items])
    stale_after = c.settings.bus_stale_after_s
    return StopArrivalsOut(
        stop=StopSummaryOut(id=stop.id, name=stop.name),
        arrivals=[
            ArrivalOut(
                **StopBusOut.of(sb, names, c.clock, stale_after).model_dump(),
                eta=EtaPredictionOut.of(p),
            )
            for sb, p in items
        ],
    )
