"""Central in-app alert service (Feature 11). Feature 10's route-deviation alerts live here too.

Alerts NOTIFY about backend state; they never change it. Every value in an alert
comes from an existing service: delay (tracking ``is_delayed``), occupancy
(Feature 8 ``capacity``), route deviation (Feature 10), ETA (Feature 5 via the
Feature 7 result), MISSED (Feature 7 decision) and the alternative (Feature 9).

Transition semantics, made idempotent with the database as the only state:

  series key  = ``TYPE|recipient|bus|trip``  (``dedup_key``; e.g. ``BUS_DELAYED|ADMIN|B07|T-…``)
  alert id    = ``ALT-<series>-<episode>``   (deterministic)
  invariant   = at most ONE active alert per series (unique partial index)

  condition true  + no active alert in the series → create (episode n+1)
  condition true  + active alert                  → nothing (or refresh the message in place)
  condition false + active alert                  → resolve (``resolved_at``; record kept)
  single-shot types (BUS_APPROACHING, MISSED_BUS) → at most one alert per series EVER,
                                                    i.e. once per trip

So repeated evaluation (3-second polling, every telemetry fix, an API restart,
a simulator restart) can never duplicate an alert. The in-process caches only
skip database reads; a cache miss falls back to the database.

Producers:
  * ``on_bus_state`` (``BusStateUpdated`` subscriber)  → BUS_DELAYED, CAPACITY_WARNING
  * ``raise_/resolve_route_deviation`` (Feature 10)   → ROUTE_DEVIATION
  * ``evaluate_student`` (``AlertMonitor`` sweep)     → BUS_APPROACHING, MISSED_BUS,
                                                        ALTERNATIVE_BUS_AVAILABLE
Bus-level alerts go to admins (one fleet alert) and to the students assigned to that
bus in the direction it is running. Lifecycle events (``AlertCreated``/``Updated``/
``Resolved``/``Read``) are published so a future WebSocket layer can push them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.auth import Principal
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.core.events import EventBus
from app.models import Alert, Bus, BusState
from app.models.alert import AlertAudience
from app.models.common import AlertType, BusStatus, Role, Severity, TripStatus
from app.models.events import AlertCreated, AlertRead, AlertResolved, AlertUpdated, BusStateUpdated
from app.repositories import Repositories
from app.services.capacity import available_seats, occupancy_percentage_display
from app.services.tracking import is_delayed

TITLE = {
    AlertType.BUS_APPROACHING: "BUS APPROACHING",
    AlertType.BUS_DELAYED: "BUS DELAYED",
    AlertType.CAPACITY_WARNING: "CAPACITY WARNING",
    AlertType.ROUTE_DEVIATION: "ROUTE DEVIATION",
    AlertType.MISSED_BUS: "MISSED BUS",
    AlertType.ALTERNATIVE_BUS_AVAILABLE: "ALTERNATIVE AVAILABLE",
}
SEVERITY = {
    AlertType.BUS_APPROACHING: Severity.INFO,
    AlertType.BUS_DELAYED: Severity.WARNING,
    AlertType.CAPACITY_WARNING: Severity.WARNING,
    AlertType.ROUTE_DEVIATION: Severity.CRITICAL,
    AlertType.MISSED_BUS: Severity.WARNING,
    AlertType.ALTERNATIVE_BUS_AVAILABLE: Severity.INFO,
}
SINGLE_PER_TRIP = frozenset({AlertType.BUS_APPROACHING, AlertType.MISSED_BUS})
STUDENT_SWEEP_TYPES = (
    AlertType.BUS_APPROACHING,
    AlertType.MISSED_BUS,
    AlertType.ALTERNATIVE_BUS_AVAILABLE,
)


# =========================================================================== keys


@dataclass(frozen=True)
class Recipient:
    """A student (``student_id``) or every admin (``student_id=None``)."""

    student_id: str | None = None

    @property
    def key(self) -> str:
        return f"S-{self.student_id}" if self.student_id else "ADMIN"

    def audience(self, route_id: str | None = None) -> AlertAudience:
        if self.student_id:
            return AlertAudience(role=Role.STUDENT, user_id=self.student_id)
        return AlertAudience(role=Role.ADMIN, route_id=route_id)


ADMINS = Recipient()


def deduplicate_key(type_: AlertType, recipient: Recipient, bus_id: str | None, trip_id: str | None) -> str:
    """Deterministic series key: the same condition for the same recipient/bus/trip."""
    return "|".join([type_.value, recipient.key, bus_id or "-", trip_id or "-"])


def alert_id(dedup_key: str, episode: int) -> str:
    return f"ALT-{dedup_key.replace('|', '-')}-{episode}"


@dataclass(frozen=True)
class AlertSpec:
    type: AlertType
    recipient: Recipient
    message: str
    ts: datetime
    bus_id: str | None = None
    """Bus the alert is about (the alternative bus for ALTERNATIVE_BUS_AVAILABLE)."""
    trip_id: str | None = None
    route_id: str | None = None
    series_bus_id: str | None = None
    """Bus used in the series key when it differs from ``bus_id`` (default: ``bus_id``)."""
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        return deduplicate_key(self.type, self.recipient, self.series_bus_id or self.bus_id, self.trip_id)


# =========================================================================== service


class AlertService:
    def __init__(self, repos: Repositories, events: EventBus, clock: Clock, settings: Settings) -> None:
        self._repos = repos
        self._events = events
        self._clock = clock
        self._settings = settings
        self._active: dict[str, bool] = {}
        """series key → has an active alert (cache of the database)."""
        self._ever: set[str] = set()
        """series keys that have had any alert (for single-shot types)."""
        self._bus_open: dict[tuple[str, AlertType], bool] = {}
        """(bus, type) → any active alert of that type for the bus (any trip, any recipient)."""
        self._last_value: dict[str, Any] = {}
        """series key → last value shown (delay minutes, alternative bus) for in-place updates."""
        self._buses: dict[str, Bus] = {}
        self._warm = False

    def forget_caches(self) -> None:
        self._active.clear()
        self._ever.clear()
        self._bus_open.clear()
        self._last_value.clear()
        self._buses.clear()
        self._warm = False

    # ------------------------------------------------------------------ core operations

    async def _is_active(self, key: str) -> bool:
        if key not in self._active:
            self._active[key] = await self._repos.alerts.active_in_series(key) is not None
        return self._active[key]

    async def _has_any(self, key: str) -> bool:
        if key in self._ever:
            return True
        if await self._repos.alerts.count_series(key) > 0:
            self._ever.add(key)
            return True
        return False

    async def create_alert(self, spec: AlertSpec) -> Alert | None:
        """Create the next episode of the series unless one is active (or, for single-shot
        types, unless the series ever had one). Returns the new alert, or None (deduplicated)."""
        key = spec.dedup_key
        if await self._is_active(key):
            return None
        if spec.type in SINGLE_PER_TRIP and await self._has_any(key):
            return None
        episode = await self._repos.alerts.count_series(key) + 1
        alert = Alert(
            id=alert_id(key, episode),
            type=spec.type,
            severity=SEVERITY[spec.type],
            audience=spec.recipient.audience(spec.route_id),
            title=TITLE[spec.type],
            body=spec.message,
            payload=spec.payload,
            created_at=spec.ts,
            bus_id=spec.bus_id,
            trip_id=spec.trip_id,
            route_id=spec.route_id,
            dedup_key=key,
            episode=episode,
        )
        if not await self._repos.alerts.insert_once(alert):  # a concurrent evaluation won
            self._active[key] = True
            self._ever.add(key)
            return None
        self._active[key] = True
        self._ever.add(key)
        if spec.bus_id:
            self._bus_open[(spec.series_bus_id or spec.bus_id, spec.type)] = True
        await self._events.publish(AlertCreated(ts=spec.ts, alert=alert))
        return alert

    async def resolve_alert(self, key: str, ts: datetime) -> Alert | None:
        """Resolve the active alert of a series (kept as a record). Idempotent."""
        if key in self._active and not self._active[key]:
            return None
        current = await self._repos.alerts.active_in_series(key)
        self._active[key] = False
        if current is None:
            return None
        return await self._close(current, ts)

    async def _close(self, a: Alert, ts: datetime) -> Alert:
        done = a.model_copy(update={"active": False, "resolved_at": ts})
        await self._repos.alerts.upsert(done)
        if a.dedup_key:
            self._active[a.dedup_key] = False
        await self._events.publish(AlertResolved(ts=ts, alert=done))
        return done

    async def update_alert(
        self, key: str, message: str, payload: dict[str, Any], ts: datetime
    ) -> Alert | None:
        """Refresh an active alert in place (no new notification; read state kept)."""
        current = await self._repos.alerts.active_in_series(key)
        if current is None:
            return None
        bus_id = payload.get("bus_id", current.bus_id)
        fresh = current.model_copy(
            update={"body": message, "payload": payload, "updated_at": ts, "bus_id": bus_id}
        )
        await self._repos.alerts.upsert(fresh)
        await self._events.publish(AlertUpdated(ts=ts, alert=fresh))
        return fresh

    async def reconcile(self, condition: bool, spec: AlertSpec) -> Alert | None:
        """Transition semantics in one call: create on entry, resolve on exit."""
        if condition:
            return await self.create_alert(spec)
        await self.resolve_alert(spec.dedup_key, spec.ts)
        return None

    # ------------------------------------------------------------------ reading / read state

    @staticmethod
    def _visible(a: Alert, principal: Principal) -> bool:
        if principal.role is Role.ADMIN:
            return a.audience.role is Role.ADMIN
        if principal.role is Role.STUDENT:
            return a.audience.user_id == principal.user_id
        return False

    async def list_for(
        self, principal: Principal, *, active: bool | None = None, unread: bool | None = None, limit: int = 50
    ) -> list[Alert]:
        """A student's own alerts, or the admins' fleet alerts. Never another student's."""
        if principal.role is Role.ADMIN:
            return await self._repos.alerts.for_recipient(
                role=Role.ADMIN.value, active=active, unread=unread, limit=limit
            )
        if principal.role is Role.STUDENT:
            return await self._repos.alerts.for_recipient(
                user_id=principal.user_id, active=active, unread=unread, limit=limit
            )
        return []

    async def get_active_alerts(self, principal: Principal, limit: int = 50) -> list[Alert]:
        return await self.list_for(principal, active=True, limit=limit)

    async def get_unread_alerts(self, principal: Principal, limit: int = 50) -> list[Alert]:
        return await self.list_for(principal, unread=True, limit=limit)

    async def mark_read(self, principal: Principal, alert_id_: str) -> Alert:
        """Mark one visible alert read (idempotent). Unknown or not-yours → 404 (no leak)."""
        a = await self._repos.alerts.get(alert_id_)
        if a is None or not self._visible(a, principal):
            raise NotFoundError(f"alert {alert_id_} not found")
        if a.read and principal.user_id in a.acked_by:
            return a
        now = self._clock.now()
        done = a.model_copy(
            update={
                "read": True,
                "read_at": a.read_at or now,
                "acked_by": sorted({*a.acked_by, principal.user_id}),
            }
        )
        await self._repos.alerts.upsert(done)
        await self._events.publish(AlertRead(ts=now, alert_id=a.id, user_id=principal.user_id))
        return done

    # ------------------------------------------------------------------ bus-level producers

    async def _bus(self, bus_id: str) -> Bus | None:
        if bus_id not in self._buses:
            bus = await self._repos.buses.get(bus_id)
            if bus is None:
                return None
            self._buses[bus_id] = bus
        return self._buses[bus_id]

    async def _students_on(self, bus_id: str, variant_id: str | None) -> list[str]:
        """Students assigned to this bus in the direction it is currently running."""
        if variant_id is None:
            return []
        return sorted(
            a.id
            for a in await self._repos.student_assignments.for_bus(bus_id)
            if a.assigned_route_direction_id == variant_id
        )

    async def _bus_is_open(self, bus_id: str, type_: AlertType) -> bool:
        k = (bus_id, type_)
        if k not in self._bus_open:
            self._bus_open[k] = bool(await self._repos.alerts.active_for_bus(bus_id, [type_.value]))
        return self._bus_open[k]

    async def _resolve_bus(
        self, bus_id: str, type_: AlertType, ts: datetime, *, except_trip: str | None = None
    ) -> None:
        """Resolve every active alert of ``type_`` about this bus (admin + students)."""
        if not await self._bus_is_open(bus_id, type_):
            return
        remaining = False
        for a in await self._repos.alerts.active_for_bus(bus_id, [type_.value]):
            if except_trip is not None and a.trip_id == except_trip:
                remaining = True
                continue
            await self._close(a, ts)
        self._bus_open[(bus_id, type_)] = remaining

    async def _bus_condition(
        self,
        type_: AlertType,
        condition: bool,
        state: BusState,
        *,
        admin_message: str,
        student_message: str,
        payload: dict[str, Any],
        value: Any,
    ) -> None:
        trip = state.trip_id
        admin = AlertSpec(
            type_, ADMINS, admin_message, state.ts, state.id, trip, state.route_id, payload=payload
        )
        if not condition:
            await self._resolve_bus(state.id, type_, state.ts)
            return
        if not await self._is_active(admin.dedup_key):
            await self._resolve_bus(state.id, type_, state.ts, except_trip=trip)  # an older trip's episode
            created = await self.create_alert(admin)
            if created is not None:
                self._last_value[admin.dedup_key] = value
                for sid in await self._students_on(state.id, state.variant_id):
                    await self.create_alert(
                        AlertSpec(
                            type_,
                            Recipient(sid),
                            student_message,
                            state.ts,
                            state.id,
                            trip,
                            state.route_id,
                            payload=payload,
                        )
                    )
            return
        if type_ is AlertType.BUS_DELAYED and self._last_value.get(admin.dedup_key) != value:
            # Still delayed but by a different number of minutes: refresh in place, no spam.
            self._last_value[admin.dedup_key] = value
            for a in await self._repos.alerts.active_for_bus(state.id, [type_.value]):
                if a.trip_id == trip and a.dedup_key:
                    msg = admin_message if a.audience.role is Role.ADMIN else student_message
                    await self.update_alert(a.dedup_key, msg, payload, state.ts)

    async def on_bus_state(self, event: BusStateUpdated) -> None:
        """BUS_DELAYED and CAPACITY_WARNING from the tracked state (existing thresholds/rules)."""
        s = event.state
        bus = await self._bus(s.id)
        if bus is None:
            return
        running = s.trip_id is not None and s.status is not BusStatus.COMPLETED
        delayed = running and is_delayed(s)
        minutes = round(s.delay_s / 60)
        await self._bus_condition(
            AlertType.BUS_DELAYED,
            delayed,
            s,
            admin_message=f"Bus {s.id} is running {minutes} minutes late ({s.variant_id}).",
            student_message=f"Bus {s.id} is running {minutes} minutes late.",
            payload={"delay_minutes": minutes, "delay_s": s.delay_s, "route_direction_id": s.variant_id},
            value=minutes,
        )
        pct = occupancy_percentage_display(s.occupancy, bus.capacity)
        full = running and pct is not None and pct >= self._settings.alert_capacity_warning_percent
        seats = available_seats(s.occupancy, bus.capacity)
        msg = f"Bus {s.id} is {pct}% full with {seats} seat{'s' if seats != 1 else ''} remaining."
        await self._bus_condition(
            AlertType.CAPACITY_WARNING,
            full,
            s,
            admin_message=msg,
            student_message=msg,
            payload={
                "occupancy": s.occupancy,
                "capacity": bus.capacity,
                "available_seats": seats,
                "occupancy_percentage": pct,
                "threshold_percent": self._settings.alert_capacity_warning_percent,
            },
            value=pct,
        )

    # ------------------------------------------------------------------ Feature 10 (route deviation)

    async def raise_route_deviation(
        self, state: BusState, distance_m: float, deviation_id: str, source: str
    ) -> Alert | None:
        """Called on the Feature 10 transition INTO a major deviation."""
        payload = {
            "kind": "route_deviation",
            "severity": "major",
            "bus_id": state.id,
            "trip_id": state.trip_id,
            "route_id": state.route_id,
            "route_direction_id": state.variant_id,
            "deviation_id": deviation_id,
            "deviation_distance_m": distance_m,
            "source": source,
        }
        admin = await self.create_alert(
            AlertSpec(
                AlertType.ROUTE_DEVIATION,
                ADMINS,
                f"BUS {state.id} is {round(distance_m)} m off its planned route.",
                state.ts,
                state.id,
                state.trip_id,
                state.route_id,
                payload=payload,
            )
        )
        if admin is not None and self._settings.alert_student_route_deviation:
            for sid in await self._students_on(state.id, state.variant_id):
                await self.create_alert(
                    AlertSpec(
                        AlertType.ROUTE_DEVIATION,
                        Recipient(sid),
                        f"Your bus {state.id} is currently {round(distance_m)} m from its planned route.",
                        state.ts,
                        state.id,
                        state.trip_id,
                        state.route_id,
                        payload=payload,
                    )
                )
        return admin

    async def resolve_route_deviation(self, bus_id: str, ts: datetime) -> None:
        """Called when the Feature 10 major deviation ends (or the trip changes)."""
        await self._resolve_bus(bus_id, AlertType.ROUTE_DEVIATION, ts)

    # ------------------------------------------------------------------ student-level producers

    async def warm_up(self) -> None:
        """Load series state for the sweep types in two queries (instead of one per student)."""
        if self._warm:
            return
        types = [t.value for t in STUDENT_SWEEP_TYPES]
        active = await self._repos.alerts.active_keys(types)
        for k in await self._repos.alerts.series_keys(types):
            self._ever.add(k)
            self._active.setdefault(k, k in active)
        self._warm = True

    async def _known_inactive(self, key: str) -> bool:
        return self._warm and key not in self._active

    async def trip_started(self, trip_id: str) -> bool:
        """Whether the trip has actually STARTED (stored status ACTIVE or COMPLETED).

        A scheduled trip has not started — e.g. a driver-controlled bus (Feature 12) waiting
        at its first stop for the driver's Start Trip, or a trip replayed after a simulator
        reset. Nobody can have missed a bus whose trip has not started.
        """
        trip = await self._repos.trips.get(trip_id)
        return trip is not None and trip.status in (TripStatus.ACTIVE, TripStatus.COMPLETED)

    async def evaluate_student(
        self, r: Any, *, boarded: bool = False, trip_started: bool | None = None
    ) -> None:
        """BUS_APPROACHING, MISSED_BUS, ALTERNATIVE_BUS_AVAILABLE for one student.

        ``r`` is a Feature 9 ``StudentRecovery`` (which carries the Feature 7 result,
        the Feature 5 prediction and the Feature 6 options). Nothing is recomputed here.
        ``trip_started`` (read fresh by the caller, else looked up here when needed) gates
        MISSED_BUS: the Feature 7 MISSED decision only counts for a trip that has started.
        """
        commute, recovery = r.commute, r.recovery
        a = commute.assignment
        sid = a.assignment.id
        me = Recipient(sid)
        ts = r.computed_at
        sb = commute.my_bus
        on_commute = sb is not None and sb.state.variant_id == a.direction.variant_id and sb.state.trip_id
        trip = sb.state.trip_id if on_commute and sb is not None else None
        bus = a.bus.id
        p = commute.prediction

        if trip is not None:
            # ---- BUS_APPROACHING: once per trip, when the Feature 5 ETA enters the window
            window_s = self._settings.alert_approaching_window_minutes * 60
            approaching = p is not None and (
                p.status == "at_stop"
                or (p.status == "predicted" and p.eta_s is not None and p.eta_s <= window_s)
            )
            key = deduplicate_key(AlertType.BUS_APPROACHING, me, bus, trip)
            if approaching and p is not None:
                n = p.eta_minutes or 0
                stop = a.boarding_stop.name
                if p.status == "at_stop":
                    msg = f"Bus {bus} is at your stop ({stop}) now."
                elif n == 0:
                    msg = f"Bus {bus} reaches your stop ({stop}) in less than a minute."
                else:
                    msg = f"Bus {bus} reaches your stop ({stop}) in {n} minute{'s' if n != 1 else ''}."
                if not (self._warm and key in self._ever):
                    await self.create_alert(
                        AlertSpec(
                            AlertType.BUS_APPROACHING,
                            me,
                            msg,
                            ts,
                            bus,
                            trip,
                            a.route.id,
                            payload={"eta_minutes": n, "stop_id": a.boarding_stop.id, "stop_name": stop},
                        )
                    )
            elif p is None or p.status in ("passed", "completed"):
                if not await self._known_inactive(key):
                    await self.resolve_alert(key, ts)

            # ---- MISSED_BUS: once per trip, when Feature 7 says MISSED (not if the student boarded)
            #      and only for a trip that has actually started (stored trip status, not the
            #      possibly-stale bus state the decision was computed from).
            mkey = deduplicate_key(AlertType.MISSED_BUS, me, bus, trip)
            missed = commute.result.decision == "MISSED" and not boarded
            active_alert = not await self._known_inactive(mkey)
            if trip_started is None and (missed or active_alert):
                trip_started = await self.trip_started(trip)
            if trip_started is False:
                # not started (driver hasn't pressed Start / trip replayed after a reset):
                # nothing can have been missed — close any alert raised from an outdated state
                if active_alert:
                    await self.resolve_alert(mkey, ts)
            elif missed:
                if not (self._warm and mkey in self._ever):
                    extra = (
                        " An alternative bus is available." if recovery.status == "recovery_available" else ""
                    )
                    await self.create_alert(
                        AlertSpec(
                            AlertType.MISSED_BUS,
                            me,
                            f"You missed your assigned bus {bus}.{extra}",
                            ts,
                            bus,
                            trip,
                            a.route.id,
                            payload={"reason": commute.result.reason},
                        )
                    )
            elif sb is not None and sb.state.status is BusStatus.COMPLETED:
                if not await self._known_inactive(mkey):
                    await self.resolve_alert(mkey, ts)

        # ---- ALTERNATIVE_BUS_AVAILABLE: while Feature 9 has a recommendation (episodic)
        akey = deduplicate_key(AlertType.ALTERNATIVE_BUS_AVAILABLE, me, bus, trip)
        rec = recovery.recommended if recovery.status == "recovery_available" else None
        if rec is not None:
            o = rec.candidate.option
            alt = o.sb.bus.id
            payload = {
                "bus_id": alt,
                "trigger": recovery.trigger,
                "eta_minutes": o.prediction.eta_minutes,
                "occupancy": o.sb.state.occupancy,
                "capacity": o.sb.bus.capacity,
                "available_seats": rec.available_seats,
                "occupancy_percentage": rec.occupancy_percentage,
                "safety_buffer_minutes": rec.candidate.spare_minutes,
                "reason": rec.reason,
            }
            created = await self.create_alert(
                AlertSpec(
                    AlertType.ALTERNATIVE_BUS_AVAILABLE,
                    me,
                    rec.reason,
                    ts,
                    alt,
                    trip,
                    a.route.id,
                    series_bus_id=bus,
                    payload=payload,
                )
            )
            if created is not None:
                self._last_value[akey] = alt
            elif self._last_value.get(akey) not in (None, alt):
                # The recommended bus changed: update the same alert, don't add another.
                self._last_value[akey] = alt
                await self.update_alert(akey, rec.reason, payload, ts)
            else:
                self._last_value.setdefault(akey, alt)
        elif not await self._known_inactive(akey):
            await self.resolve_alert(akey, ts)
