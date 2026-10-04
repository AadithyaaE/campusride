"""Driver App backend (Feature 12) — the driver-facing control surface of the EXISTING system.

Everything is derived from the signed-in driver: ``User → Driver (by user) → Bus
(``bus.driver_id``) → today's trips``. The driver never passes a bus, route or trip.

* Start / Stop Trip delegate to the existing ``BusSimulator`` (driver-controlled
  buses, ``SIM_DRIVER_CONTROLLED_BUSES``): the same trip timeline and synthetic GPS
  flow through the same ``TelemetryIngestService`` → tracking → ``BusState`` that the
  Student and Admin dashboards read. Trip status changes use the existing trip
  repository + ``TripStarted``/``TripEnded`` events.
* Live values (speed, stops, occupancy, delay, route status) are read from ``BusState``
  and the existing helpers (Feature 8 capacity, ``is_stale``). Nothing is computed twice.

Feature 12 uses synthetic GPS. Actual device GPS is not implemented yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.core.auth import Principal
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import CodedError, ServiceUnavailableError
from app.models import Bus, BusState, Driver, Route, Stop, Trip
from app.models.common import TripStatus
from app.repositories import Repositories
from app.services.bus_simulator import BusSimulator
from app.services.tracking import is_stale

GpsState = Literal["LIVE", "STALE", "UNAVAILABLE"]
TripState = Literal["READY", "ACTIVE", "COMPLETED", "NO_TRIP", "NO_ASSIGNMENT"]


@dataclass(frozen=True)
class DriverContext:
    driver: Driver
    bus: Bus | None
    route: Route | None
    trips: list[Trip]
    """Today's trips for the bus, by departure."""
    trip: Trip | None
    """The trip the driver is on (active) or would start next (else the last one)."""
    trip_state: TripState
    control: Literal["driver", "schedule"]
    state: BusState | None
    gps: GpsState
    stops: dict[str, Stop]


def gps_state(state: BusState | None, *, now, stale_after_s: float) -> GpsState:
    """From backend telemetry freshness only (``BUS_STALE_AFTER_S``)."""
    if state is None:
        return "UNAVAILABLE"
    return "STALE" if is_stale(state, now, stale_after_s) else "LIVE"


class DriverService:
    def __init__(
        self, repos: Repositories, settings: Settings, clock: Clock, simulator: BusSimulator | None
    ) -> None:
        self._repos = repos
        self._settings = settings
        self._clock = clock
        self._sim = simulator

    async def _driver(self, principal: Principal) -> Driver:
        driver = await self._repos.drivers.by_user(principal.user_id)
        if driver is None:
            raise CodedError("invalid_driver", "No driver profile is linked to this account.", 404)
        return driver

    async def _bus_of(self, driver: Driver) -> Bus | None:
        return next((b for b in await self._repos.buses.list() if b.driver_id == driver.id), None)

    def _service_date(self) -> date:
        return self._clock.local_now().date()

    async def context(self, principal: Principal) -> DriverContext:
        driver = await self._driver(principal)
        bus = await self._bus_of(driver)
        if bus is None:
            return DriverContext(
                driver, None, None, [], None, "NO_ASSIGNMENT", "schedule", None, "UNAVAILABLE", {}
            )
        route = await self._repos.routes.get(bus.default_route_id)
        trips = sorted(
            await self._repos.trips.for_bus_on(bus.id, self._service_date()), key=lambda t: t.scheduled_start
        )
        driven = self._sim is not None and self._sim.is_driver_controlled(bus.id)
        active = next((t for t in trips if t.status is TripStatus.ACTIVE), None)
        upcoming = next((t for t in trips if t.status is TripStatus.SCHEDULED), None)
        trip = active or upcoming or (trips[-1] if trips else None)
        if active is not None:
            trip_state: TripState = "ACTIVE"
        elif upcoming is not None:
            trip_state = "READY"
        elif trips:
            trip_state = "COMPLETED"
        else:
            trip_state = "NO_TRIP"
        state = await self._repos.bus_states.get(bus.id)
        ids = {s.stop_id for s in (route.variant(trip.variant_id).stops if route and trip else [])}
        for sid in (state.current_stop_id, state.next_stop_id) if state else ():
            if sid:
                ids.add(sid)
        stops = {s.id: s for s in await self._repos.stops.get_many(sorted(ids))}
        return DriverContext(
            driver=driver,
            bus=bus,
            route=route,
            trips=trips,
            trip=trip,
            trip_state=trip_state,
            control="driver" if driven else "schedule",
            state=state,
            gps=gps_state(state, now=self._clock.now(), stale_after_s=self._settings.bus_stale_after_s),
            stops=stops,
        )

    def _simulator(self) -> BusSimulator:
        if self._sim is None:
            raise ServiceUnavailableError("The trip simulator is not running.")
        return self._sim

    async def _require_bus(self, principal: Principal) -> Bus:
        bus = await self._bus_of(await self._driver(principal))
        if bus is None:
            raise CodedError(
                "no_assignment", "You have no bus assigned. Please contact the transport office."
            )
        return bus

    async def start_trip(self, principal: Principal) -> DriverContext:
        """Start the driver's OWN next trip (verified, then handed to the existing simulator)."""
        bus = await self._require_bus(principal)
        await self._simulator().start_driver_trip(bus.id)
        return await self.context(principal)

    async def stop_trip(self, principal: Principal) -> DriverContext:
        bus = await self._require_bus(principal)
        await self._simulator().stop_driver_trip(bus.id)
        return await self.context(principal)

    async def simulate_gps(self, principal: Principal) -> DriverContext:
        """One synthetic fix for the driver's bus NOW (backend simulator → telemetry → tracking)."""
        bus = await self._require_bus(principal)
        sent = await self._simulator().emit_now(bus.id)
        if sent is None:
            raise CodedError("gps_unavailable", "No trip is running, so there is no GPS to simulate.")
        return await self.context(principal)
