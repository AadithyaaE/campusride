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
from typing import cast

from app.core.auth import Principal, sim_driver_principal
from app.core.clock import ALLOWED_SIM_SPEEDS, SimClock, derive_seed
from app.core.config import Settings
from app.core.errors import CodedError
from app.models import Bus, BusState, Trip
from app.models.common import BusSource, FleetStatus, TripStatus
from app.models.telemetry_in import TelemetryBatchIn, TelemetryPointIn
from app.repositories import Repositories
from app.seed.loader import load_schedule
from app.seed.trips import build_trips
from app.services.tracking import TelemetryIngestService
from app.simulator.bus_agent import PRE_TRIP_WINDOW_S, AgentState, BusPlan, TripPlan, build_trip_plan
from app.simulator.deviation import MODES, DeviationMode, offset_point
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
    route_deviation: dict[str, str] | None = None
    driver_controlled_buses: tuple[str, ...] = ()
    """Demo deviation modes in force: ``{"*": mode}`` for all buses and/or per bus id."""


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
        self._deviation: dict[str, DeviationMode] = {}
        self._driver_buses: frozenset[str] = frozenset(
            b.strip() for b in settings.sim_driver_controlled_buses.split(",") if b.strip()
        )
        """Feature 12: buses whose trips start/stop from the Driver App."""
        self._driver_active: dict[str, tuple[TripPlan, datetime]] = {}
        self._driver_done: set[str] = set()
        """Feature 10 demo: ``"*"`` = every bus, else per bus id. Empty = all normal."""

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

    def set_route_deviation(self, mode: str, bus_id: str | None = None) -> SimulatorStatus:
        """Demo: shift simulated GPS off the planned route (all buses, or one bus).

        The route geometry is never touched — only the synthetic position the
        simulator reports, which then flows through telemetry → tracking.
        """
        if mode not in MODES:
            raise ValueError(f"mode must be one of {list(MODES)}")
        m = cast(DeviationMode, mode)
        if bus_id is None:
            self._deviation = {} if m == "normal" else {"*": m}
        else:
            if bus_id not in self._plans:
                raise KeyError(bus_id)
            if m == "normal" and "*" not in self._deviation:
                self._deviation.pop(bus_id, None)
            else:
                self._deviation[bus_id] = m
        return self.status()

    def deviation_for(self, bus_id: str) -> DeviationMode:
        return self._deviation.get(bus_id, self._deviation.get("*", "normal"))

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
            route_deviation=dict(self._deviation),
            driver_controlled_buses=tuple(sorted(self._driver_buses)),
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
        await repos.boarding_events.delete_for_buses(sim_ids)  # trips replay from the start
        await repos.alerts.delete_for_buses(sim_ids)  # …so do their alerts (Feature 11)
        self._ingest.alerts.forget_caches()
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
        self._deviation = {}  # reset / restart always returns to NORMAL
        self._driver_active = {}  # …and driver-controlled buses wait for their driver
        self._driver_done = set()
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

    # ------------------------------------------------------------------ sampling

    def _sample(self, bus_id: str, plan: BusPlan, ts: datetime) -> tuple[TripPlan, AgentState] | None:
        """Where the synthetic bus is at ``ts`` (ground truth), or None when its phone is quiet."""
        if bus_id in self._driver_buses:
            return self._driver_sample(bus_id, plan, ts)
        trip_plan = plan.plan_at(ts)
        if trip_plan is None:
            return None
        s = trip_plan.at(ts)
        if s.phase == "done":
            # Like a driver ending the trip: one final fix, then the phone goes quiet
            # until the next trip's pre-departure window.
            if s.trip_id in self._finished_trips:
                return None
            self._finished_trips.add(s.trip_id)
        return trip_plan, s

    def _driver_sample(self, bus_id: str, plan: BusPlan, ts: datetime) -> tuple[TripPlan, AgentState] | None:
        """Driver-controlled bus (Feature 12): the SAME trip timeline, anchored at the driver's
        actual start; before Start Trip it waits at its first stop (pre-departure window)."""
        active = self._driver_active.get(bus_id)
        if active is not None:
            tp, started = active
            s = tp.at(tp.start + (ts - started))
            if s.phase == "done":  # reached the campus terminal: final fix, then quiet
                self._driver_active.pop(bus_id, None)
                self._driver_done.add(tp.trip.id)
            return tp, s
        nxt = self.next_driver_trip(bus_id)
        if nxt is None or (ts - nxt.start).total_seconds() < -PRE_TRIP_WINDOW_S:
            return None
        return nxt, nxt.at(nxt.start - timedelta(seconds=1))  # "pre": waiting at the first stop

    async def _send(
        self, bus_id: str, trip_plan: TripPlan, s: AgentState, ts: datetime, noise_key: str
    ) -> BusState:
        sigma = self._settings.sim_gps_noise_sigma_m
        noise_rng = random.Random(derive_seed(self._settings.seed, "gps", bus_id, noise_key))
        truth = s.lnglat
        mode = self.deviation_for(bus_id)
        if mode != "normal" and s.phase != "done":
            offset = (
                self._settings.sim_deviation_minor_offset_m
                if mode == "minor"
                else self._settings.sim_deviation_major_offset_m
            )
            truth = offset_point(truth, s.heading_deg, offset, trip_plan.line)
        (lng, lat), accuracy = jitter(truth, sigma, noise_rng)
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
        return await self._ingest.ingest(batch, self._principals[bus_id])

    async def _emit(self, ts: datetime) -> None:
        k = round((ts - self._grid_start).total_seconds() / self._interval)
        for bus_id, plan in self._plans.items():
            sample = self._sample(bus_id, plan, ts)
            if sample is None:
                continue
            await self._send(bus_id, sample[0], sample[1], ts, str(k))
        self._emissions += 1

    # ------------------------------------------------------------------ driver control (Feature 12)

    def is_driver_controlled(self, bus_id: str) -> bool:
        return bus_id in self._driver_buses

    def active_driver_trip(self, bus_id: str) -> TripPlan | None:
        active = self._driver_active.get(bus_id)
        return active[0] if active else None

    def next_driver_trip(self, bus_id: str) -> TripPlan | None:
        """The bus's first trip today not yet driven (what Start Trip would start)."""
        plan = self._plans.get(bus_id)
        if plan is None:
            return None
        return next((tp for tp in plan.trips if tp.trip.id not in self._driver_done), None)

    async def start_driver_trip(self, bus_id: str) -> TripPlan:
        """Start the bus's next trip NOW: same timeline/telemetry pipeline, anchored at now."""
        async with self._lock:
            if bus_id not in self._driver_buses:
                raise CodedError("schedule_controlled", f"Bus {bus_id} runs on the automatic demo schedule.")
            if bus_id in self._driver_active:
                raise CodedError("trip_already_active", "A trip is already active on this bus.")
            tp = self.next_driver_trip(bus_id)
            if tp is None:
                raise CodedError("no_trip", f"Bus {bus_id} has no more trips today.")
            now = self._clock.now()
            trip = await self._ingest.start_trip(tp.trip.id, now)
            if trip.status is not TripStatus.ACTIVE:
                self._driver_done.add(tp.trip.id)
                raise CodedError("trip_completed", f"Trip {tp.trip.id} is already {trip.status.value}.")
            self._driver_active[bus_id] = (tp, now)
            s = tp.at(tp.start)
            await self._send(bus_id, tp, s, now, f"start-{now.timestamp()}")
            return tp

    async def stop_driver_trip(self, bus_id: str) -> TripPlan:
        """Finalize the active trip where the bus is now; its telemetry then stops."""
        async with self._lock:
            active = self._driver_active.get(bus_id)
            if active is None:
                raise CodedError("no_active_trip", "There is no active trip to stop.")
            tp, started = active
            now = self._clock.now()
            s = tp.at(tp.start + (now - started))
            await self._ingest.end_trip(tp.trip.id, now)
            self._driver_active.pop(bus_id, None)
            self._driver_done.add(tp.trip.id)
            # one final fix through the normal pipeline → tracking derives COMPLETED there
            await self._send(bus_id, tp, s, now, f"stop-{now.timestamp()}")
            return tp

    async def emit_now(self, bus_id: str) -> BusState | None:
        """Simulate GPS: push one synthetic fix for this bus right now (same pipeline).
        Useful while the simulation is paused or between grid ticks. None if the phone is quiet."""
        async with self._lock:
            plan = self._plans.get(bus_id)
            if plan is None:
                return None
            now = self._clock.now()
            if bus_id in self._driver_buses:
                sample = self._driver_sample(bus_id, plan, now)
            else:
                tp = plan.plan_at(now)
                sample = (tp, tp.at(now)) if tp is not None else None
            if sample is None:
                return None
            return await self._send(bus_id, sample[0], sample[1], now, f"manual-{now.timestamp()}")

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
