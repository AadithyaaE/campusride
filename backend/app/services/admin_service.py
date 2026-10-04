"""Transport admin dashboard (Feature 13) — read models over the EXISTING system.

Nothing here tracks, matches, predicts or classifies on its own. Each fleet row is
assembled from:

* ``BusState`` (tracking, Feature 3/4) — position, speed, stops, status, delay;
* Feature 5 ``EtaService.predict`` on a Feature 4 ``MatchingService`` position — ETA
  to the bus's next stop;
* Feature 8 ``capacity`` helpers — seats and occupancy %; Feature 6 ``crowding_level``;
* Feature 10 ``live_route_status`` + ``BusState.deviation_m``;
* tracking's ``is_delayed`` (the same rule the alerts and the student app use);
* Feature 11 alerts (the admins' active fleet alerts);
* the Feature 12 driver assignment (``bus.driver_id``) and today's trips.

The only new rules are presentation-level aggregates (counts, sums, averages of these
backend values) and ``operational_status`` — one control-room label per bus.

Historical analytics do not exist yet, so ``synthetic_analytics`` returns clearly
labelled, deterministic demo series (seeded from ``SEED`` + the service date).
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.auth import Principal
from app.core.clock import Clock, derive_seed
from app.core.config import Settings
from app.models import Alert, Bus, BusState, Driver, Route, Stop, Trip
from app.models.api.admin import (
    AdminAnalyticsOut,
    AdminFleetBusOut,
    AdminFleetOut,
    AdminOverviewOut,
    AdminRouteDirectionOut,
    AdminRouteOut,
    AdminScheduleOut,
    AlertCountsOut,
    AlertRefOut,
    DelaySummaryOut,
    FilterOptionOut,
    FleetFilterOptionsOut,
    LabelValueOut,
    LiveAnalyticsOut,
    NamedRefOut,
    OccupancyBarOut,
    OperationalStatus,
    ScheduleTripOut,
    SyntheticAnalyticsOut,
    TripCountsOut,
)
from app.models.api.route_status import LatLonOut
from app.models.common import BusStatus, FleetStatus, Role, RouteStatus, Severity, TripStatus
from app.repositories import Repositories
from app.services.alert_service import AlertService
from app.services.bus_comparison_service import crowding_level, delay_minutes
from app.services.bus_simulator import BusSimulator
from app.services.capacity import available_seats, occupancy_percentage_display
from app.services.driver_service import gps_state
from app.services.eta_service import EtaService
from app.services.matching import MatchingService
from app.services.ridership import RidershipLedger
from app.services.route_anomaly_service import live_route_status
from app.services.tracking import is_delayed

ADMIN_VIEW = Principal(user_id="admin-dashboard", role=Role.ADMIN, name="admin dashboard")
"""Reads the shared fleet alerts (every admin sees the same set)."""

STATUS_LABELS: dict[OperationalStatus, str] = {
    "active": "Active",
    "delayed": "Delayed",
    "deviated": "Deviated",
    "breakdown": "Breakdown",
    "waiting": "Waiting to depart",
    "completed": "Trip completed",
    "idle": "Idle",
    "out_of_service": "Out of service",
}
DEVIATIONS = (RouteStatus.MINOR_DEVIATION, RouteStatus.MAJOR_DEVIATION)
ON_TRIP: tuple[OperationalStatus, ...] = ("active", "delayed", "deviated", "breakdown")
"""Operational statuses of a bus that is out on a running trip."""
PASSENGERS_METHOD = (
    "Sum over today's started trips of the peak on-board load (Feature 8 occupancy: "
    "synthetic simulator headcount + QR boardings), observed by the backend."
)
SYNTHETIC_METHOD = (
    "Deterministic demo series: Python random.Random seeded with "
    "derive_seed(SEED, 'admin-analytics', <series>, <service date>). Same seed and date → same values."
)


def operational_status(
    bus: Bus, state: BusState | None, route_status: RouteStatus | None
) -> OperationalStatus:
    """One control-room label per bus, from backend state only (first match wins)."""
    if bus.status is not FleetStatus.ACTIVE:
        return "out_of_service"
    if state is None or state.trip_id is None:
        return "idle"
    if state.status is BusStatus.COMPLETED:
        return "completed"
    if state.status is BusStatus.BREAKDOWN:
        return "breakdown"
    if route_status is RouteStatus.MAJOR_DEVIATION or state.status is BusStatus.DEVIATED:
        return "deviated"
    if is_delayed(state):
        return "delayed"
    if state.status in (BusStatus.EN_ROUTE, BusStatus.DWELLING):
        return "active"
    return "waiting"


def trip_counts(trips: list[Trip]) -> TripCountsOut:
    c = Counter(t.status for t in trips)
    return TripCountsOut(
        total=len(trips),
        scheduled=c[TripStatus.SCHEDULED],
        active=c[TripStatus.ACTIVE],
        completed=c[TripStatus.COMPLETED],
        cancelled=c[TripStatus.CANCELLED],
    )


def _alert_ref(a: Alert) -> AlertRefOut:
    return AlertRefOut(alert_id=a.id, type=a.type.value, severity=a.severity, title=a.title, message=a.body)


@dataclass(frozen=True)
class _Reference:
    routes: dict[str, Route]
    stops: dict[str, Stop]
    drivers: dict[str, Driver]


class AdminService:
    def __init__(
        self,
        repos: Repositories,
        settings: Settings,
        clock: Clock,
        matching: MatchingService,
        eta: EtaService,
        alerts: AlertService,
        ridership: RidershipLedger,
        simulator: BusSimulator | None,
    ) -> None:
        self._repos = repos
        self._settings = settings
        self._clock = clock
        self._matching = matching
        self._eta = eta
        self._alerts = alerts
        self._ridership = ridership
        self._sim = simulator
        self._ref: _Reference | None = None

    # ------------------------------------------------------------------ static reference data

    async def _reference(self) -> _Reference:
        """Routes, stops and drivers are seeded reference data — cached for the app's lifetime."""
        if self._ref is None:
            self._ref = _Reference(
                routes={r.id: r for r in await self._repos.routes.list()},
                stops={s.id: s for s in await self._repos.stops.list()},
                drivers={d.id: d for d in await self._repos.drivers.list()},
            )
        return self._ref

    def forget_caches(self) -> None:
        self._ref = None

    def service_date(self) -> date:
        return self._clock.local_now().date()

    async def _trips_today(self) -> list[Trip]:
        return sorted(await self._repos.trips.on_date(self.service_date()), key=lambda t: t.scheduled_start)

    async def _active_admin_alerts(self) -> list[Alert]:
        return await self._alerts.list_for(ADMIN_VIEW, active=True, limit=500)

    # ------------------------------------------------------------------ fleet

    async def _fleet_rows(self, *, with_eta: bool, only: str | None = None) -> list[AdminFleetBusOut]:
        ref = await self._reference()
        now = self._clock.now()
        stale_after = self._settings.bus_stale_after_s
        if only is None:
            buses = await self._repos.buses.list()
            states = {s.id: s for s in await self._repos.bus_states.list()}
        else:
            one, state = await self._repos.buses.get(only), await self._repos.bus_states.get(only)
            buses = [one] if one else []
            states = {state.id: state} if state else {}
        trips = {t.id: t for t in await self._trips_today()}
        alerts_by_bus: dict[str, list[Alert]] = defaultdict(list)
        for a in await self._active_admin_alerts():
            bus_id = a.bus_id or a.payload.get("bus_id")
            if bus_id:
                alerts_by_bus[bus_id].append(a)

        def stop_ref(stop_id: str | None) -> NamedRefOut | None:
            s = ref.stops.get(stop_id or "")
            return NamedRefOut(id=s.id, name=s.name) if s else None

        rows: list[AdminFleetBusOut] = []
        for bus in buses:
            s = states.get(bus.id)
            route = ref.routes.get(s.route_id if s and s.route_id else bus.default_route_id)
            assigned = ref.routes.get(bus.default_route_id)
            driver = ref.drivers.get(bus.driver_id or "")
            rs = live_route_status(s, now=now, stale_after_s=stale_after) if s else None
            on_trip = s is not None and s.trip_id is not None
            trip = trips.get(s.trip_id) if s and s.trip_id else None
            if trip is None and s and s.trip_id:
                trip = await self._repos.trips.get(s.trip_id)
            label = None
            if on_trip and route is not None and s is not None and s.variant_id:
                try:
                    label = route.variant(s.variant_id).label
                except KeyError:
                    label = None
            eta_min = eta_status = eta_conf = None
            moving_on = s is not None and on_trip and s.status is not BusStatus.COMPLETED
            if with_eta and moving_on and s is not None and s.next_stop_id:
                sb = await self._matching.position_of(bus, s, s.next_stop_id)
                if sb is not None and sb.match is not None:
                    pred = await self._eta.predict(sb)
                    eta_min, eta_status, eta_conf = pred.eta_minutes, pred.status, pred.confidence
            pct = occupancy_percentage_display(s.occupancy, bus.capacity) if s else None
            rows.append(
                AdminFleetBusOut(
                    bus_id=bus.id,
                    reg_no=bus.reg_no,
                    source=bus.source,
                    fleet_status=bus.status,
                    route_id=bus.default_route_id,
                    route_name=assigned.name if assigned else bus.default_route_id,
                    route_color=assigned.color if assigned else "#64748b",
                    driver=NamedRefOut(id=driver.id, name=driver.name) if driver else None,
                    operational_status=operational_status(bus, s, rs),
                    bus_status=s.status if s else None,
                    trip_id=s.trip_id if s else None,
                    trip_status=trip.status if trip else None,
                    route_direction_id=s.variant_id if s else None,
                    direction=s.direction if s else None,
                    direction_label=label,
                    location=LatLonOut(lat=s.location.lat, lon=s.location.lng) if s else None,
                    heading_deg=s.heading_deg if s else None,
                    speed_kmh=round(s.speed_mps * 3.6) if s else None,
                    current_stop=stop_ref(s.current_stop_id) if s else None,
                    next_stop=stop_ref(s.next_stop_id) if s else None,
                    eta_next_stop_min=eta_min,
                    eta_status=eta_status,
                    eta_confidence=eta_conf,
                    delay_s=s.delay_s if on_trip and s else None,
                    delay_min=delay_minutes(s.delay_s) if on_trip and s else None,
                    is_delayed=bool(s and is_delayed(s)),
                    occupancy=s.occupancy if s else None,
                    capacity=bus.capacity,
                    available_seats=available_seats(s.occupancy, bus.capacity) if s else None,
                    occupancy_percentage=pct,
                    crowding=crowding_level(pct),
                    boarded_count=s.boarded_count if s else 0,
                    route_status=rs,
                    deviation_distance_m=s.deviation_m if s else None,
                    route_progress=s.route_progress if s else None,
                    gps=gps_state(s, now=now, stale_after_s=stale_after),
                    gps_age_s=max(0, round((now - s.last_seen).total_seconds())) if s else None,
                    last_updated=s.ts if s else None,
                    active_alerts=[_alert_ref(a) for a in alerts_by_bus.get(bus.id, [])],
                )
            )
        return rows

    async def fleet_row(self, bus_id: str) -> AdminFleetBusOut | None:
        """One bus's row — the same assembly as ``fleet`` (used by the Feature 14 realtime push)."""
        rows = await self._fleet_rows(with_eta=True, only=bus_id)
        return rows[0] if rows else None

    async def fleet(
        self, *, route_id: str | None = None, bus_id: str | None = None, status: str | None = None
    ) -> AdminFleetOut:
        rows = await self._fleet_rows(with_eta=True)
        ref = await self._reference()
        filtered = [
            r
            for r in rows
            if (route_id is None or r.route_id == route_id)
            and (bus_id is None or r.bus_id == bus_id)
            and (status is None or r.operational_status == status)
        ]
        return AdminFleetOut(
            generated_at=self._clock.now(),
            sim_time=self._clock.local_now(),
            filters={"route_id": route_id, "bus_id": bus_id, "status": status},
            total=len(rows),
            buses=filtered,
            options=FleetFilterOptionsOut(
                routes=[FilterOptionOut(value=r.id, label=f"{r.id} · {r.name}") for r in ref.routes.values()],
                buses=[FilterOptionOut(value=r.bus_id, label=f"Bus {r.bus_id}") for r in rows],
                statuses=[FilterOptionOut(value=k, label=v) for k, v in STATUS_LABELS.items()],
            ),
        )

    # ------------------------------------------------------------------ overview

    async def _passengers(self, trips: list[Trip]) -> int:
        return sum(
            self._ridership.peak(t.id) for t in trips if t.status in (TripStatus.ACTIVE, TripStatus.COMPLETED)
        )

    async def _qr_boardings(self, trips: list[Trip]) -> int:
        return sum([await self._repos.boarding_events.count_for_trip(t.id) for t in trips])

    async def overview(self) -> AdminOverviewOut:
        rows = await self._fleet_rows(with_eta=False)
        trips = await self._trips_today()
        alerts = await self._active_admin_alerts()
        sev = Counter(a.severity for a in alerts)
        return AdminOverviewOut(
            generated_at=self._clock.now(),
            sim_time=self._clock.local_now(),
            service_date=self.service_date(),
            simulation_paused=self._sim.status().paused if self._sim else None,
            total_buses=len(rows),
            buses_in_service=sum(r.fleet_status is FleetStatus.ACTIVE for r in rows),
            buses_on_trip=sum(r.operational_status in ON_TRIP for r in rows),
            active_trips=sum(t.status is TripStatus.ACTIVE for t in trips),
            trips_today=trip_counts(trips),
            students=await self._repos.users.count(filter={"role": Role.STUDENT.value}),
            assigned_students=await self._repos.student_assignments.count(),
            passengers_today=await self._passengers(trips),
            passengers_method=PASSENGERS_METHOD,
            qr_boardings_today=await self._qr_boardings(trips),
            delayed_buses=sum(r.is_delayed for r in rows),
            deviated_buses=sum(r.route_status in DEVIATIONS for r in rows),
            major_deviations=sum(r.route_status is RouteStatus.MAJOR_DEVIATION for r in rows),
            alerts=AlertCountsOut(
                active=len(alerts),
                unread=sum(not a.read for a in alerts),
                critical=sev[Severity.CRITICAL],
                warning=sev[Severity.WARNING],
                info=sev[Severity.INFO],
            ),
        )

    # ------------------------------------------------------------------ routes & schedule

    async def routes(self) -> list[AdminRouteOut]:
        ref = await self._reference()
        rows = await self._fleet_rows(with_eta=False)
        trips = await self._trips_today()
        out: list[AdminRouteOut] = []
        for route in ref.routes.values():
            mine = [r for r in rows if r.route_id == route.id]
            running = [r for r in mine if r.operational_status in ON_TRIP]
            pcts = [r.occupancy_percentage for r in running if r.occupancy_percentage is not None]
            route_trips = [t for t in trips if t.route_id == route.id]

            def stop(stop_id: str) -> NamedRefOut:
                s = ref.stops.get(stop_id)
                return NamedRefOut(id=stop_id, name=s.name if s else stop_id)

            out.append(
                AdminRouteOut(
                    id=route.id,
                    name=route.name,
                    color=route.color,
                    length_km=round(route.length_m / 1000, 1),
                    directions=[
                        AdminRouteDirectionOut(
                            variant_id=d.variant_id,
                            direction=d.direction,
                            label=d.label,
                            stop_count=len(d.stops),
                            first_stop=stop(d.stops[0].stop_id),
                            last_stop=stop(d.stops[-1].stop_id),
                            scheduled_duration_min=round(
                                (d.stops[-1].scheduled_offset_s - d.stops[0].scheduled_offset_s) / 60
                            ),
                        )
                        for d in route.directions
                    ],
                    assigned_buses=[r.bus_id for r in mine],
                    active_buses=[r.bus_id for r in running],
                    trips_today=trip_counts(route_trips),
                    delayed_buses=[r.bus_id for r in mine if r.is_delayed],
                    deviated_buses=[r.bus_id for r in mine if r.route_status in DEVIATIONS],
                    avg_occupancy_percentage=round(sum(pcts) / len(pcts)) if pcts else None,
                    passengers_today=await self._passengers(route_trips),
                )
            )
        return out

    async def schedule(self, *, route_id: str | None = None) -> AdminScheduleOut:
        ref = await self._reference()
        buses = {b.id: b for b in await self._repos.buses.list()}
        states = {s.id: s for s in await self._repos.bus_states.list()}
        out: list[ScheduleTripOut] = []
        for t in await self._trips_today():
            if route_id is not None and t.route_id != route_id:
                continue
            route = ref.routes.get(t.route_id)
            if route is None:
                continue
            d = route.variant(t.variant_id)
            bus = buses.get(t.bus_id)
            driver = ref.drivers.get(t.driver_id or (bus.driver_id if bus else "") or "")
            s = states.get(t.bus_id)
            live = s is not None and s.trip_id == t.id and t.status is TripStatus.ACTIVE
            first, last = d.stops[0], d.stops[-1]
            out.append(
                ScheduleTripOut(
                    trip_id=t.id,
                    route_id=t.route_id,
                    route_name=route.name,
                    route_color=route.color,
                    route_direction_id=t.variant_id,
                    direction=t.direction,
                    direction_label=d.label,
                    first_stop=ref.stops[first.stop_id].name if first.stop_id in ref.stops else first.stop_id,
                    last_stop=ref.stops[last.stop_id].name if last.stop_id in ref.stops else last.stop_id,
                    scheduled_departure=t.scheduled_start,
                    scheduled_arrival=t.scheduled_start
                    + timedelta(seconds=last.scheduled_offset_s - first.scheduled_offset_s),
                    actual_start=t.actual_start,
                    actual_end=t.actual_end,
                    bus_id=t.bus_id,
                    reg_no=bus.reg_no if bus else t.bus_id,
                    driver=NamedRefOut(id=driver.id, name=driver.name) if driver else None,
                    status=t.status,
                    delay_min=delay_minutes(s.delay_s) if live and s else None,
                )
            )
        return AdminScheduleOut(service_date=self.service_date(), generated_at=self._clock.now(), trips=out)

    # ------------------------------------------------------------------ analytics

    async def analytics(self) -> AdminAnalyticsOut:
        ref = await self._reference()
        rows = await self._fleet_rows(with_eta=False)
        trips = await self._trips_today()
        tz = self._clock.tz

        passengers_by_route: dict[str, int] = {r: 0 for r in ref.routes}
        for t in trips:
            if t.status in (TripStatus.ACTIVE, TripStatus.COMPLETED):
                carried = self._ridership.peak(t.id)
                passengers_by_route[t.route_id] = passengers_by_route.get(t.route_id, 0) + carried

        running = [r for r in rows if r.operational_status in ON_TRIP]
        delays_by_route: dict[str, list[int]] = defaultdict(list)
        for r in running:
            if r.delay_s is not None:
                delays_by_route[r.route_id].append(r.delay_s)
        all_delays = [d for ds in delays_by_route.values() for d in ds]

        by_hour = Counter(t.scheduled_start.astimezone(tz).hour for t in trips)
        slots: Counter[str] = Counter()
        for t in trips:
            for e in await self._repos.boarding_events.for_trip(t.id):
                local = e.ts.astimezone(tz)
                slots[f"{local.hour:02d}:{0 if local.minute < 30 else 30:02d}"] += 1

        def route_label(rid: str) -> LabelValueOut:
            route = ref.routes.get(rid)
            return LabelValueOut(label=rid, key=rid, value=0, color=route.color if route else None)

        live = LiveAnalyticsOut(
            passengers_per_route=[
                route_label(rid).model_copy(update={"value": v}) for rid, v in passengers_by_route.items()
            ],
            occupancy_by_bus=[
                OccupancyBarOut(
                    bus_id=r.bus_id,
                    route_id=r.route_id,
                    occupancy=r.occupancy or 0,
                    capacity=r.capacity,
                    occupancy_percentage=r.occupancy_percentage,
                    crowding=r.crowding,
                )
                for r in running
            ],
            trips_today=trip_counts(trips),
            trips_by_departure_hour=[
                LabelValueOut(label=f"{h:02d}:00", value=n) for h, n in sorted(by_hour.items())
            ],
            average_delay=DelaySummaryOut(
                buses_measured=len(all_delays),
                fleet_avg_delay_min=round(sum(all_delays) / len(all_delays) / 60, 1) if all_delays else None,
                by_route=[
                    route_label(rid).model_copy(update={"value": round(sum(ds) / len(ds) / 60, 1)})
                    for rid, ds in sorted(delays_by_route.items())
                ],
            ),
            qr_boardings_by_slot=[LabelValueOut(label=k, value=v) for k, v in sorted(slots.items())],
        )
        return AdminAnalyticsOut(
            generated_at=self._clock.now(),
            service_date=self.service_date(),
            live=live,
            synthetic=synthetic_analytics(self._settings.seed, self.service_date(), ref.routes),
        )


def synthetic_analytics(seed: int, service_date: date, routes: dict[str, Route]) -> SyntheticAnalyticsOut:
    """Deterministic demo history — the same seed and service date always give the same numbers."""

    def rng(series: str) -> random.Random:
        return random.Random(derive_seed(seed, "admin-analytics", series, service_date.isoformat()))

    days = [service_date - timedelta(days=i) for i in range(7, 0, -1)]
    r = rng("daily-passengers")
    daily = [
        LabelValueOut(
            label=d.strftime("%a %d"),
            key=d.isoformat(),
            value=0 if d.weekday() == 6 else r.randint(380, 520),  # no service on Sundays
        )
        for d in days
    ]
    r = rng("average-delay")
    delay = [
        LabelValueOut(label=d.strftime("%a %d"), key=d.isoformat(), value=round(r.uniform(1.0, 6.5), 1))
        for d in days
    ]
    r = rng("peak-boarding")
    # weekday shape: a sharp morning peak (to campus) and a flatter evening one (from campus)
    shape = {6: 0.15, 7: 1.0, 8: 0.7, 9: 0.1, 12: 0.05, 13: 0.08, 15: 0.1, 16: 0.75, 17: 0.55, 18: 0.3}
    peak = [
        LabelValueOut(label=f"{h:02d}:00", value=round(220 * w * r.uniform(0.85, 1.15)))
        for h, w in shape.items()
    ]
    r = rng("route-weekly")
    per_route = [
        LabelValueOut(label=rid, key=rid, value=r.randint(55, 95), color=route.color)
        for rid, route in routes.items()
    ]
    return SyntheticAnalyticsOut(
        method=SYNTHETIC_METHOD,
        seed=seed,
        daily_passengers=daily,
        average_delay_by_day=delay,
        peak_boarding_by_hour=peak,
        passengers_per_route_weekly_avg=per_route,
    )
