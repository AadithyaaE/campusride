"""Realtime hub (Feature 14): existing EventBus → WebSocket clients.

    services ──publish──▶ InProcessEventBus ──▶ RealtimeHub ──▶ ConnectionManager ──▶ sockets

The hub is a SUBSCRIBER of the one existing event bus. It never computes transport
facts: every payload is a DTO the REST API already returns, built by the existing code
(``bus_out`` → ``GET /buses``, ``AdminService.fleet_row`` → ``GET /admin/fleet`` incl. the
Feature 5 ETA, ``DriverService`` → ``GET /driver/me``, ``AlertOut`` → ``GET /alerts``).
What the hub adds is DISTRIBUTION only:

* audience — who may receive each message (see ``manager.Audience``);
* change detection — ``occupancy.updated`` / ``eta.updated`` / ``route.deviation`` are sent
  only when the backend value differs from the last one pushed for that bus;
* coalescing — ``BusStateUpdated`` events are cheap to record (the simulator awaits event
  handlers) and are flushed per bus at most every ``WS_FLUSH_INTERVAL_S`` (latest state
  wins), so 12 buses at 20× never flood a client;
* ordering — a state older than the last one pushed for a bus is dropped; every envelope
  carries a unique ``id`` and an increasing ``seq``.

Trip, boarding and alert events are pushed immediately (they are rare).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.core.ids import new_id
from app.models import Alert, BusState
from app.models.common import Role, RouteStatus
from app.models.events import (
    AlertCreated,
    AlertRead,
    AlertResolved,
    AlertUpdated,
    BoardingRecorded,
    BusStateUpdated,
    SimReset,
    TripEnded,
    TripStarted,
)
from app.realtime.manager import Audience, Connection, ConnectionManager
from app.realtime.messages import (
    AlertReadData,
    BoardingData,
    EtaData,
    NamedRef,
    OccupancyData,
    RouteDeviationData,
    Scope,
    TripEventData,
    WsEnvelope,
    WsEventType,
)

if TYPE_CHECKING:
    from app.deps import AppContainer

log = logging.getLogger(__name__)

DEVIATIONS = (RouteStatus.MINOR_DEVIATION, RouteStatus.MAJOR_DEVIATION)


@dataclass(frozen=True)
class _Pushed:
    """What was last pushed for one bus (for change detection and ordering)."""

    ts: datetime
    trip_id: str | None
    status: str
    occupancy: int
    route_status: RouteStatus | None
    eta: tuple | None


class RealtimeHub:
    def __init__(self, container: AppContainer) -> None:
        self._c = container
        s = container.settings
        self.manager = ConnectionManager(s.ws_queue_size)
        self._seq = itertools.count(1)
        self._pending: dict[str, BusState] = {}
        self._pushed: dict[str, _Pushed] = {}
        self._overview_dirty = False
        self._overview_at = 0.0
        self._task: asyncio.Task | None = None
        self._flush_lock = asyncio.Lock()
        self.flushes = 0

    # ------------------------------------------------------------------ wiring

    def attach(self) -> None:
        """Subscribe to the EXISTING event bus (once per container)."""
        ev = self._c.events
        tag = id(self)
        ev.subscribe(BusStateUpdated, self.on_bus_state, name=f"realtime.bus_state.{tag}")
        ev.subscribe(TripStarted, self.on_trip_started, name=f"realtime.trip_started.{tag}")
        ev.subscribe(TripEnded, self.on_trip_ended, name=f"realtime.trip_ended.{tag}")
        ev.subscribe(BoardingRecorded, self.on_boarding, name=f"realtime.boarding.{tag}")
        ev.subscribe(AlertCreated, self.on_alert, name=f"realtime.alert_created.{tag}")
        ev.subscribe(AlertUpdated, self.on_alert, name=f"realtime.alert_updated.{tag}")
        ev.subscribe(AlertResolved, self.on_alert, name=f"realtime.alert_resolved.{tag}")
        ev.subscribe(AlertRead, self.on_alert_read, name=f"realtime.alert_read.{tag}")
        ev.subscribe(SimReset, self.on_sim_reset, name=f"realtime.sim_reset.{tag}")

    def ensure_loop(self) -> None:
        """Start the flush loop (idempotent; lifespan or first connection)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="realtime-flush")

    async def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        for conn in self.manager.connections:
            conn.close("shutdown")

    async def _run(self) -> None:
        interval = self._c.settings.ws_flush_interval_s
        while True:
            await asyncio.sleep(interval)
            try:
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception:  # never let one bad push stop live updates
                log.exception("realtime flush failed")

    # ------------------------------------------------------------------ envelopes

    def envelope(
        self, type_: WsEventType, data: BaseModel | dict[str, Any], scope: Scope, ts: datetime
    ) -> str:
        payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
        return WsEnvelope(
            id=f"evt-{new_id()}",
            type=type_,
            seq=next(self._seq),
            ts=ts,
            sent_at=datetime.now(UTC),
            scope=scope,
            data=payload,
        ).model_dump_json()

    def _send(
        self, type_: WsEventType, data: BaseModel | dict, audience: Audience, scope: Scope, ts: datetime
    ) -> int:
        if not len(self.manager):
            return 0
        return self.manager.send(self.envelope(type_, data, scope, ts), audience)

    def hello(self, conn: Connection) -> str:
        from app.realtime.messages import HelloData

        s = self._c.settings
        return self.envelope(
            "hello",
            HelloData(
                user_id=conn.principal.user_id,
                role=conn.principal.role.value,
                bus_id=conn.bus_id,
                heartbeat_s=s.ws_heartbeat_s,
                flush_interval_s=s.ws_flush_interval_s,
            ),
            "user",
            self._c.clock.now(),
        )

    def ping(self) -> str:
        return self.envelope("ping", {}, "system", self._c.clock.now())

    # ------------------------------------------------------------------ event handlers (cheap)

    async def on_bus_state(self, e: BusStateUpdated) -> None:
        cur = self._pending.get(e.state.id)
        if cur is None or e.state.ts >= cur.ts:
            self._pending[e.state.id] = e.state

    async def on_trip_started(self, e: TripStarted) -> None:
        self._overview_dirty = True
        data = TripEventData(
            trip_id=e.trip_id, bus_id=e.bus_id, route_id=e.route_id, route_direction_id=e.variant_id
        )
        self._send("trip.started", data, Audience.fleet(e.bus_id), "fleet", e.ts)

    async def on_trip_ended(self, e: TripEnded) -> None:
        self._overview_dirty = True
        trip = await self._c.repos.trips.get(e.trip_id)
        data = TripEventData(
            trip_id=e.trip_id,
            bus_id=e.bus_id,
            route_id=trip.route_id if trip else None,
            route_direction_id=e.variant_id,
        )
        self._send("trip.completed", data, Audience.fleet(e.bus_id), "fleet", e.ts)

    async def on_boarding(self, e: BoardingRecorded) -> None:
        self._overview_dirty = True
        full = BoardingData(trip_id=e.trip_id, bus_id=e.bus_id, stop_id=e.stop_id, student_id=e.student_id)
        self._send("boarding.updated", full, Audience.admins(), "admin", e.ts)
        if e.student_id:
            self._send("boarding.updated", full, Audience.user(e.student_id), "user", e.ts)
        anon = full.model_copy(update={"student_id": None})
        self._send("boarding.updated", anon, Audience(driver_bus=e.bus_id), "driver", e.ts)

    @staticmethod
    def _alert_audience(a: Alert) -> tuple[Audience, Scope] | None:
        if a.audience.role is Role.ADMIN:
            return Audience.admins(), "admin"
        if a.audience.user_id:
            return Audience.user(a.audience.user_id), "user"
        return None  # never broadcast an alert without a recipient

    async def on_alert(self, e: AlertCreated | AlertUpdated | AlertResolved) -> None:
        from app.models.api.route_status import AlertOut

        target = self._alert_audience(e.alert)
        if target is None:
            return
        self._overview_dirty = True
        type_: WsEventType = (
            "alert.created"
            if isinstance(e, AlertCreated)
            else "alert.updated"
            if isinstance(e, AlertUpdated)
            else "alert.resolved"
        )
        self._send(type_, AlertOut.of(e.alert), target[0], target[1], e.ts)

    async def on_alert_read(self, e: AlertRead) -> None:
        if not len(self.manager):
            return
        a = await self._c.repos.alerts.get(e.alert_id)
        target = self._alert_audience(a) if a else None
        if target is None:
            return
        self._overview_dirty = True
        # admin alerts share one read flag → every admin; a student's alert → that student
        self._send("alert.read", AlertReadData(alert_id=e.alert_id, read=True), target[0], target[1], e.ts)

    async def on_sim_reset(self, e: SimReset) -> None:
        self._pending.clear()
        self._pushed.clear()
        self._overview_dirty = True
        self._send("sim.reset", {"scenario": e.scenario}, Audience.everyone(), "system", e.ts)

    # ------------------------------------------------------------------ flush (coalesced bus updates)

    async def flush(self) -> int:
        """Push the latest state of every bus that changed since the last flush."""
        async with self._flush_lock:
            pending, self._pending = self._pending, {}
            self.flushes += 1
            sent = 0
            for bus_id in sorted(pending):
                sent += await self._push_bus(pending[bus_id])
            sent += await self._push_overview()
            return sent

    async def _push_bus(self, state: BusState) -> int:
        from app.api.v1.buses import bus_out

        prev = self._pushed.get(state.id)
        if prev is not None and state.ts < prev.ts:
            return 0  # out of order: something newer was already pushed
        if not len(self.manager):
            self._pushed[state.id] = _Pushed(
                state.ts, state.trip_id, state.status.value, state.occupancy, state.route_status, None
            )
            return 0
        c = self._c
        bus = await c.repos.buses.get(state.id)
        if bus is None:
            return 0
        out = bus_out(bus, state, c)
        live = out.live
        assert live is not None
        fleet, ts, sent = Audience.fleet(bus.id), state.ts, 0
        sent += self._send("bus.state.updated", {"bus": out.model_dump(mode="json")}, fleet, "fleet", ts)

        if prev is None or prev.occupancy != live.occupancy or prev.trip_id != live.trip_id:
            occ = OccupancyData(
                bus_id=bus.id,
                trip_id=live.trip_id,
                passengers=live.occupancy,
                capacity=bus.capacity,
                available_seats=live.available_seats,
                percentage=live.occupancy_percentage,
                boarded_count=live.boarded_count,
            )
            sent += self._send("occupancy.updated", occ, fleet, "fleet", ts)

        rs = live.route_status
        entering_or_leaving = rs in DEVIATIONS or (prev is not None and prev.route_status in DEVIATIONS)
        if prev is not None and rs != prev.route_status and entering_or_leaving:
            dev = RouteDeviationData(
                bus_id=bus.id,
                trip_id=live.trip_id,
                route_status=rs,
                previous_status=prev.route_status,
                deviation_distance_m=live.deviation_distance_m,
            )
            sent += self._send("route.deviation", dev, fleet, "fleet", ts)

        row = await c.admin().fleet_row(bus.id)  # Feature 5 ETA + the admin row, as REST builds them
        eta_key = None
        if row is not None:
            nxt = row.next_stop
            eta_key = (row.trip_id, nxt.id if nxt else None, row.eta_next_stop_min, row.eta_status)
            if prev is None or prev.eta != eta_key:
                eta = EtaData(
                    bus_id=bus.id,
                    trip_id=row.trip_id,
                    next_stop=NamedRef(id=nxt.id, name=nxt.name) if nxt else None,
                    eta_minutes=row.eta_next_stop_min,
                    status=row.eta_status,
                    confidence=row.eta_confidence,
                )
                sent += self._send("eta.updated", eta, fleet, "fleet", ts)
            if self.manager.has_role(Role.ADMIN):
                admin_row = {"bus": row.model_dump(mode="json")}
                sent += self._send("fleet.bus.updated", admin_row, Audience.admins(), "admin", ts)

        drivers = self.manager.drivers_of(bus.id)
        if drivers:
            from app.models.api.driver import DriverDashboardOut
            from app.services.driver_service import DriverService

            svc = DriverService(c.repos, c.settings, c.clock, c.simulator)
            for conn in drivers:
                dash = DriverDashboardOut.of(await svc.context(conn.principal))
                sent += self.manager.send_to(conn, self.envelope("driver.state.updated", dash, "driver", ts))

        if prev is None or (prev.trip_id, prev.status, prev.occupancy, prev.route_status) != (
            live.trip_id,
            live.status.value,
            live.occupancy,
            rs,
        ):
            self._overview_dirty = True
        self._pushed[bus.id] = _Pushed(ts, live.trip_id, live.status.value, live.occupancy, rs, eta_key)
        return sent

    async def _push_overview(self) -> int:
        if not self._overview_dirty or not self.manager.has_role(Role.ADMIN):
            return 0
        now = time.monotonic()
        if now - self._overview_at < self._c.settings.ws_overview_min_interval_s:
            return 0  # stays dirty; pushed on a later flush
        self._overview_dirty = False
        self._overview_at = now
        o = await self._c.admin().overview()
        return self._send("admin.overview.updated", o, Audience.admins(), "admin", self._c.clock.now())
