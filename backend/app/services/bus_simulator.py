"""Synthetic bus simulator service — a fleet of fake driver phones.

    SimClock → BusSimulator → synthetic telemetry → TelemetryIngestService.ingest
             (the same function behind POST /api/v1/driver/telemetry)
             → tracking → BusState → API (and WebSocket consumers later)

* Movement comes from ``app.simulator.bus_agent`` (deterministic timelines on
  the real route geometry); this service only schedules, emits and controls.
* Telemetry is emitted on a FIXED simulated-time grid (start + k × interval),
  so the result does not depend on how fast the event loop happens to run:
  same SEED + start time + sim time ⇒ same telemetry ⇒ same bus state.
* Lifecycle is owned by the FastAPI lifespan: exactly one background task per
  simulator, at most one running simulator per process, cancelled on shutdown.
* Time is the existing ``SimClock`` (1/2/5/10/20×, pause/resume/reset).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.core.auth import Principal, sim_driver_principal
from app.core.clock import ALLOWED_SIM_SPEEDS, SimClock, derive_seed
from app.core.config import Settings
from app.models import Bus, Trip
from app.models.common import BusSource, FleetStatus, TripStatus
from app.models.telemetry_in import TelemetryBatchIn, TelemetryPointIn
from app.repositories import Repositories
from app.seed.loader import load_schedule
from app.seed.trips import build_trips
from app.services.tracking import TelemetryIngestService
from app.simulator.bus_agent import BusPlan, build_trip_plan
from app.simulator.gps_noise import jitter
from app.simulator.traffic import TrafficModel

log = logging.getLogger(__name__)

REAL_TICK_S = 0.25
"""How often (wall time) the loop checks the clock for due emissions."""
MAX_CATCH_UP = 24
"""If more emissions than this are overdue (e.g. after a stall), skip to the latest."""

_RUNNING: weakref.WeakSet[BusSimulator] = weakref.WeakSet()


class SimulatorAlreadyRunning(RuntimeError):
    pass


@dataclass(frozen=True)
class SimulatorStatus:
    running: bool
    paused: bool
    speed: float
    sim_time: datetime
    local_time: datetime
    start_time: datetime
    service_date: str | None
    buses: int
    emissions: int
    telemetry_interval_s: float
    allowed_speeds: tuple[int, ...] = ALLOWED_SIM_SPEEDS


class BusSimulator:
    def __init__(
        self,
        repos: Repositories,
        clock: SimClock,
        ingest: TelemetryIngestService,
        settings: Settings,
        *,
        seed_dir: Path | None = None,
    ) -> None:
        self._repos = repos
        self._clock = clock
        self._ingest = ingest
        self._settings = settings
        self._seed_dir = seed_dir or settings.seed_data_dir
        self._interval = float(settings.sim_telemetry_interval_s)
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._plans: dict[str, BusPlan] = {}
        self._principals: dict[str, Principal] = {}
        self._grid_start: datetime = clock.start
        self._k = 0
        self._emissions = 0
        self._service_date: str | None = None
        self._finished_trips: set[str] = set()

    # ------------------------------------------------------------------ lifecycle

    @property
    def task_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def ensure_loop(self) -> bool:
        """Start the background task if it isn't running. Returns True if started."""
        if self.task_running:
            return False
        others = [s for s in _RUNNING if s is not self and s.task_running]
        if others:
            raise SimulatorAlreadyRunning("another bus simulator is already running in this process")
        self._task = asyncio.create_task(self._run(), name="campusride-bus-simulator")
        _RUNNING.add(self)
        log.info("bus simulator loop started")
        return True

    async def shutdown(self) -> None:
        task, self._task = self._task, None
        _RUNNING.discard(self)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        log.info("bus simulator stopped")

    async def start(self) -> SimulatorStatus:
        """Resume simulated time (and make sure the loop runs)."""
        self.ensure_loop()
        self._clock.resume()
        return self.status()

    async def pause(self) -> SimulatorStatus:
        self._clock.pause()
        return self.status()

    async def reset(self) -> SimulatorStatus:
        """Back to the clock's start time: fresh trips, buses at their first stops."""
        async with self._lock:
            self._clock.reset()
            await self._prepare()
        return self.status()

    def set_speed(self, speed: float) -> SimulatorStatus:
        self._clock.set_speed(speed)
        return self.status()

    def status(self) -> SimulatorStatus:
        return SimulatorStatus(
            running=self.task_running and not self._clock.paused,
            paused=self._clock.paused,
            speed=self._clock.speed,
            sim_time=self._clock.now(),
            local_time=self._clock.local_now(),
            start_time=self._clock.start,
            service_date=self._service_date,
            buses=len(self._plans),
            emissions=self._emissions,
            telemetry_interval_s=self._interval,
        )

    # ------------------------------------------------------------------ preparation

    async def _prepare(self) -> None:
        """Load the synthetic world for the clock's service date and emit the initial fixes."""
        repos = self._repos
        tz = self._clock.tz
        service_date = self._clock.start.astimezone(tz).date()
        self._service_date = service_date.isoformat()

        buses = [
            b
            for b in await repos.buses.list()
            if b.source is BusSource.SIM and b.status is FleetStatus.ACTIVE
        ]
        routes = {r.id: r for r in await repos.routes.list()}
        traffic = TrafficModel(await repos.traffic_profiles.list())
        trips = await self._ensure_trips(service_date, await repos.buses.list())

        # Fresh run: forget previous synthetic state (device buses are untouched).
        sim_ids = [b.id for b in buses]
        for bus_id in sim_ids:
            await repos.bus_states.delete(bus_id)
        await repos.telemetry.delete_for_buses(sim_ids)
        self._ingest.forget_caches()

        drivers = {d.id: d for d in await repos.drivers.list()}
        self._plans, self._principals = {}, {}
        for bus in buses:
            own = sorted((t for t in trips if t.bus_id == bus.id), key=lambda t: t.scheduled_start)
            plans = [
                build_trip_plan(t, routes[t.route_id], bus, traffic, seed=self._settings.seed, tz=tz)
                for t in own
                if t.route_id in routes
            ]
            if not plans:
                continue
            self._plans[bus.id] = BusPlan(bus=bus, trips=plans)
            driver = drivers.get(bus.driver_id or "")
            self._principals[bus.id] = sim_driver_principal(
                bus.id, driver.user_id if driver else f"sim-{bus.id}"
            )

        self._grid_start = self._clock.start
        self._finished_trips = set()
        self._k = 0
        self._emissions = 0
        await self._emit(self._grid_start)  # initial fixes at t0
        self._k = 1
        log.info("simulator prepared: %d buses, service date %s", len(self._plans), service_date)

    async def _ensure_trips(self, service_date, all_buses: list[Bus]) -> list[Trip]:
        trips = await self._repos.trips.on_date(service_date)
        if not trips:
            trips = build_trips(load_schedule(self._seed_dir), all_buses, service_date, self._clock.tz)
            await self._repos.trips.insert_many(trips)
            return trips
        fresh: list[Trip] = []
        for t in trips:
            if t.status is not TripStatus.SCHEDULED or t.actual_start or t.actual_end:
                t = t.model_copy(
                    update={"status": TripStatus.SCHEDULED, "actual_start": None, "actual_end": None}
                )
                await self._repos.trips.upsert(t)
            fresh.append(t)
        return fresh

    # ------------------------------------------------------------------ running

    async def step_until(self, now: datetime) -> int:
        """Emit every grid point ≤ ``now`` that hasn't been emitted. Returns emissions made."""
        async with self._lock:
            due = int((now - self._grid_start).total_seconds() // self._interval) - self._k + 1
            if due <= 0:
                return 0
            if due > MAX_CATCH_UP:
                self._k += due - 1
                due = 1
            for _ in range(due):
                await self._emit(self._grid_start + timedelta(seconds=self._k * self._interval))
                self._k += 1
            return due

    async def _emit(self, ts: datetime) -> None:
        k = round((ts - self._grid_start).total_seconds() / self._interval)
        sigma = self._settings.sim_gps_noise_sigma_m
        for bus_id, plan in self._plans.items():
            trip_plan = plan.plan_at(ts)
            if trip_plan is None:
                continue
            s = trip_plan.at(ts)
            if s.phase == "done":
                # Like a driver ending the trip: one final fix, then the phone goes quiet
                # until the next trip's pre-departure window.
                if s.trip_id in self._finished_trips:
                    continue
                self._finished_trips.add(s.trip_id)
            noise_rng = random.Random(derive_seed(self._settings.seed, "gps", bus_id, str(k)))
            (lng, lat), accuracy = jitter(s.lnglat, sigma, noise_rng)
            batch = TelemetryBatchIn(
                bus_id=bus_id,
                trip_id=s.trip_id,
                points=[
                    TelemetryPointIn(
                        ts=ts,
                        lng=lng,
                        lat=lat,
                        speed_mps=round(s.speed_mps, 2),
                        heading_deg=s.heading_deg % 360,
                        accuracy_m=accuracy,
                        occupancy=s.occupancy,
                    )
                ],
            )
            await self._ingest.ingest(batch, self._principals[bus_id])
        self._emissions += 1

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(REAL_TICK_S)
            if self._clock.paused:
                continue
            try:
                await self.step_until(self._clock.now())
            except asyncio.CancelledError:
                raise
            except Exception:  # keep the demo alive; log and continue
                log.exception("simulator tick failed")

    # ------------------------------------------------------------------ introspection (tests/admin)

    def plan(self, bus_id: str) -> BusPlan | None:
        return self._plans.get(bus_id)
