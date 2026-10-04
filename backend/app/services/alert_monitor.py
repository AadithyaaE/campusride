"""Periodic student-alert sweep (Feature 11): approaching / missed / alternative.

Runs on the simulation clock every ``ALERT_EVALUATION_INTERVAL_S`` (and at least
``ALERT_EVALUATION_MIN_WALL_S`` apart in wall time). It evaluates every ASSIGNED
student through the existing Feature 9 → 7 → 6 → 5 → 4 chain in batch (one Feature 6
comparison per bus/stop/direction group) and hands each result to
``AlertService.evaluate_student``. Student requests never trigger it, so polling
``GET /alerts`` stays a cheap indexed read.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime

from app.core.clock import Clock
from app.core.config import Settings
from app.repositories import Repositories
from app.services.alert_service import AlertService
from app.services.missed_bus_service import MissedBusService

log = logging.getLogger(__name__)
REAL_TICK_S = 0.5


class AlertMonitor:
    def __init__(
        self,
        alerts: AlertService,
        recovery: MissedBusService,
        repos: Repositories,
        clock: Clock,
        settings: Settings,
    ) -> None:
        self._alerts = alerts
        self._recovery = recovery
        self._repos = repos
        self._clock = clock
        self._settings = settings
        self._last_sim: datetime | None = None
        self._last_wall = 0.0
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.sweeps = 0

    async def sweep(self) -> int:
        """Evaluate every assigned student once. Returns the number evaluated."""
        async with self._lock:
            await self._alerts.warm_up()
            ids = sorted(a.id for a in await self._repos.student_assignments.list(limit=1_000_000))
            results = await self._recovery.for_students(ids)
            for r in results:
                trip = r.commute.my_bus.state.trip_id if r.commute.my_bus is not None else None
                boarded = False
                started: bool | None = None
                if trip is not None and r.commute.result.decision == "MISSED":
                    sid = r.commute.assignment.assignment.id
                    boarded = await self._repos.boarding_events.for_student_trip(sid, trip) is not None
                    # read NOW (not at sweep start): a reset / driver may have changed the trip
                    started = await self._alerts.trip_started(trip)
                await self._alerts.evaluate_student(r, boarded=boarded, trip_started=started)
            self.sweeps += 1
            self._last_sim = self._clock.now()
            self._last_wall = time.monotonic()
            return len(results)

    def due(self) -> bool:
        now = self._clock.now()
        if self._last_sim is None or now < self._last_sim:  # first run, or the clock was reset
            return True
        sim_gap = (now - self._last_sim).total_seconds()
        wall_gap = time.monotonic() - self._last_wall
        return sim_gap >= self._settings.alert_evaluation_interval_s and (
            wall_gap >= self._settings.alert_evaluation_min_wall_s
        )

    def reset(self) -> None:
        self._last_sim = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(REAL_TICK_S)
            try:
                if self.due():
                    await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:  # keep alerts flowing; log and continue
                log.exception("alert sweep failed")

    def ensure_loop(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="alert-monitor")

    async def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
