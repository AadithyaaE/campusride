"""Reference data queries: stops and routes.

Read-only lookups over the static network. The "which routes serve this
stop" query here is the foundation the Phase 3 matching service builds on.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import NotFoundError
from app.models import GeoPoint, Route, RouteDirection, Stop
from app.models.route import RouteStop
from app.repositories import Repositories

MAX_NEARBY_RADIUS_M = 5_000.0


@dataclass(frozen=True)
class ServiceAtStop:
    """A route direction that serves a given stop."""

    route: Route
    direction: RouteDirection
    route_stop: RouteStop


class ReferenceService:
    def __init__(self, repos: Repositories) -> None:
        self._repos = repos

    async def list_stops(self) -> list[Stop]:
        return await self._repos.stops.list()

    async def get_stop(self, stop_id: str) -> Stop:
        stop = await self._repos.stops.get(stop_id)
        if stop is None:
            raise NotFoundError(f"stop {stop_id} not found")
        return stop

    async def nearby_stops(
        self, lng: float, lat: float, radius_m: float, limit: int
    ) -> list[tuple[Stop, float]]:
        radius_m = min(radius_m, MAX_NEARBY_RADIUS_M)
        return await self._repos.stops.near(GeoPoint.of(lng, lat), radius_m, limit)

    async def services_at_stop(self, stop_id: str) -> list[ServiceAtStop]:
        """Every route direction serving the stop, ordered by variant id."""
        await self.get_stop(stop_id)
        out: list[ServiceAtStop] = []
        for route in await self._repos.routes.serving_stop(stop_id):
            for direction in route.directions:
                rs = direction.stop(stop_id)
                if rs is not None:
                    out.append(ServiceAtStop(route=route, direction=direction, route_stop=rs))
        out.sort(key=lambda s: (s.route.id, s.direction.variant_id))
        return out

    async def list_routes(self) -> list[Route]:
        return await self._repos.routes.list()

    async def get_route(self, route_id: str) -> Route:
        route = await self._repos.routes.get(route_id)
        if route is None:
            raise NotFoundError(f"route {route_id} not found")
        return route

    async def route_with_stops(self, route_id: str) -> tuple[Route, dict[str, Stop]]:
        route = await self.get_route(route_id)
        ids = {s.stop_id for d in route.directions for s in d.stops}
        stops = {s.id: s for s in await self._repos.stops.get_many(list(ids))}
        return route, stops
