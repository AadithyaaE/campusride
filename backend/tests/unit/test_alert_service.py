"""Feature 11 — central alert service: lifecycle, dedup, the six triggers, simulator runs."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.auth import Principal
from app.core.errors import NotFoundError
from app.models.common import AlertType, BusStatus, Role, Severity
from app.models.events import AlertCreated, AlertRead, AlertResolved, BusStateUpdated
from app.services.alert_service import (
    ADMINS,
    AlertService,
    AlertSpec,
    Recipient,
    alert_id,
    deduplicate_key,
)
from tests.unit.test_bus_comparison import _advance, pred
from tests.unit.test_eta import MIDDAY, make_state

T0 = MIDDAY
ME = Principal(user_id="U-S0001", role=Role.STUDENT)
OTHER = Principal(user_id="U-S0002", role=Role.STUDENT)
ADMIN = Principal(user_id="U-A1", role=Role.ADMIN)


def svc(container) -> AlertService:
    return container.alerts()


def spec(type_=AlertType.BUS_DELAYED, student="U-S0001", trip="T1", ts=T0, bus="B05", msg="Bus B05 is late."):
    return AlertSpec(type_, Recipient(student), msg, ts, bus, trip, "R3")


async def all_alerts(container):
    return await container.repos.alerts.recent(limit=10_000)


# =========================================================================== core lifecycle


async def test_create_alert_fields_unread_and_timestamp(container):
    s = svc(container)
    seen = []
    container.events.subscribe(AlertCreated, lambda e: _record(seen, e), name="t.created")
    a = await s.create_alert(spec())
    assert a is not None
    assert a.id == alert_id("BUS_DELAYED|S-U-S0001|B05|T1", 1) == "ALT-BUS_DELAYED-S-U-S0001-B05-T1-1"
    assert (a.type, a.title, a.body, a.bus_id, a.trip_id) == (
        AlertType.BUS_DELAYED,
        "BUS DELAYED",
        "Bus B05 is late.",
        "B05",
        "T1",
    )
    assert a.student_id == "U-S0001" and a.audience.role is Role.STUDENT
    assert a.severity is Severity.WARNING and a.created_at == T0
    assert a.read is False and a.active is True and a.resolved_at is None
    assert [e.alert.id for e in seen] == [a.id]  # published for a future WebSocket layer


async def _record(seen, e):
    seen.append(e)


def test_deterministic_dedup_keys():
    k = deduplicate_key(AlertType.BUS_APPROACHING, Recipient("U-S0001"), "B05", "T1")
    assert k == deduplicate_key(AlertType.BUS_APPROACHING, Recipient("U-S0001"), "B05", "T1")
    assert k == "BUS_APPROACHING|S-U-S0001|B05|T1"
    assert deduplicate_key(AlertType.ROUTE_DEVIATION, ADMINS, "B05", "T1") == "ROUTE_DEVIATION|ADMIN|B05|T1"


@pytest.mark.parametrize(
    ("type_", "severity"),
    [
        (AlertType.BUS_APPROACHING, Severity.INFO),
        (AlertType.BUS_DELAYED, Severity.WARNING),
        (AlertType.CAPACITY_WARNING, Severity.WARNING),
        (AlertType.ROUTE_DEVIATION, Severity.CRITICAL),
        (AlertType.MISSED_BUS, Severity.WARNING),
        (AlertType.ALTERNATIVE_BUS_AVAILABLE, Severity.INFO),
    ],
)
async def test_severity_per_type(container, type_, severity):
    a = await svc(container).create_alert(spec(type_))
    assert a.severity is severity


async def test_dedup_repeated_evaluation_and_episodes(container):
    s = svc(container)
    for _ in range(5):
        await s.reconcile(True, spec())
    assert len(await all_alerts(container)) == 1  # repeated evaluation → no duplicate
    await s.reconcile(False, spec(ts=T0 + timedelta(minutes=1)))
    (resolved,) = await all_alerts(container)
    assert resolved.active is False and resolved.resolved_at == T0 + timedelta(minutes=1)
    await s.reconcile(True, spec(ts=T0 + timedelta(minutes=2)))  # condition returns → new episode
    alerts = sorted(await all_alerts(container), key=lambda a: a.episode)
    assert [a.episode for a in alerts] == [1, 2] and alerts[1].id.endswith("-T1-2")


async def test_dedup_survives_a_restart(container):
    await svc(container).create_alert(spec())
    fresh = AlertService(container.repos, container.events, container.clock, container.settings)
    assert await fresh.create_alert(spec()) is None  # no in-memory state needed
    assert len(await all_alerts(container)) == 1


async def test_single_shot_types_once_per_trip(container):
    s = svc(container)
    first = await s.create_alert(spec(AlertType.BUS_APPROACHING))
    await s.resolve_alert(first.dedup_key, T0)
    assert await s.create_alert(spec(AlertType.BUS_APPROACHING)) is None  # same trip: never again
    assert await s.create_alert(spec(AlertType.BUS_APPROACHING, trip="T2")) is not None  # next trip


async def test_separate_trips_and_students(container):
    s = svc(container)
    assert await s.create_alert(spec(trip="T1")) is not None
    assert await s.create_alert(spec(trip="T2")) is not None
    assert await s.create_alert(spec(student="U-S0002")) is not None
    assert len(await all_alerts(container)) == 3


async def test_concurrent_creation_is_atomic(container):
    import asyncio

    s = svc(container)
    results = await asyncio.gather(*(s.create_alert(spec()) for _ in range(6)))
    assert sum(r is not None for r in results) == 1


async def test_read_active_unread_filters_and_ownership(container):
    s = svc(container)
    reads = []
    container.events.subscribe(AlertRead, lambda e: _record(reads, e), name="t.read")
    mine = await s.create_alert(spec())
    old = await s.create_alert(spec(trip="T0"))
    await s.resolve_alert(old.dedup_key, T0)
    theirs = await s.create_alert(spec(student="U-S0002"))
    fleet = await s.create_alert(AlertSpec(AlertType.BUS_DELAYED, ADMINS, "Bus B05 late.", T0, "B05", "T1"))

    assert {a.id for a in await s.list_for(ME)} == {mine.id, old.id}  # never another student's
    assert [a.id for a in await s.get_active_alerts(ME)] == [mine.id]
    assert [a.id for a in await s.list_for(ME, active=False)] == [old.id]
    assert [a.id for a in await s.list_for(ADMIN)] == [fleet.id]  # admins: fleet only, no personal alerts

    done = await s.mark_read(ME, mine.id)
    assert done.read and done.read_at is not None and "U-S0001" in done.acked_by
    again = await s.mark_read(ME, mine.id)  # idempotent
    assert again.read_at == done.read_at
    assert [a.id for a in await s.get_unread_alerts(ME)] == [old.id]
    assert len(reads) == 1
    with pytest.raises(NotFoundError):
        await s.mark_read(ME, theirs.id)  # another student's alert: 404, nothing leaks
    with pytest.raises(NotFoundError):
        await s.mark_read(ME, "ALT-NOPE")
    with pytest.raises(NotFoundError):
        await s.mark_read(ADMIN, mine.id)  # admins don't manage students' personal alerts
    assert (await s.mark_read(ADMIN, fleet.id)).read is True
    assert await s.list_for(Principal(user_id="U-D01", role=Role.DRIVER)) == []


async def test_resolve_publishes_and_keeps_the_record(container):
    s = svc(container)
    resolved = []
    container.events.subscribe(AlertResolved, lambda e: _record(resolved, e), name="t.resolved")
    a = await s.create_alert(spec())
    await s.resolve_alert(a.dedup_key, T0)
    await s.resolve_alert(a.dedup_key, T0)  # idempotent
    assert len(resolved) == 1 and await container.repos.alerts.get(a.id) is not None


# =========================================================================== BUS_DELAYED / CAPACITY_WARNING


def b05(*, delay_s=0, occupancy=10, trip="T-R3", status=BusStatus.EN_ROUTE, ts=T0):
    s = make_state("R3", 4_000, bus="B05", delay_s=delay_s, status=status, ts=ts)
    return s.model_copy(update={"occupancy": occupancy, "trip_id": trip})


async def push(container, state):
    await svc(container).on_bus_state(BusStateUpdated(ts=state.ts, state=state))


async def by(container, type_, role=None):
    out = [a for a in await all_alerts(container) if a.type is type_]
    if role is not None:
        out = [a for a in out if a.audience.role is role]
    return sorted(out, key=lambda a: (a.created_at, a.id))


async def test_bus_delayed_transitions(container):
    await push(container, b05(delay_s=200))  # below the existing 5-min rule
    assert await by(container, AlertType.BUS_DELAYED) == []
    await push(container, b05(delay_s=480))
    admin = await by(container, AlertType.BUS_DELAYED, Role.ADMIN)
    students = await by(container, AlertType.BUS_DELAYED, Role.STUDENT)
    assert len(admin) == 1 and admin[0].body.startswith("Bus B05 is running 8 minutes late")
    assigned = {a.id for a in await container.repos.student_assignments.for_bus("B05")}
    assert {a.student_id for a in students} <= assigned and "U-S0001" in {a.student_id for a in students}
    assert students[0].body == "Bus B05 is running 8 minutes late."
    n = len(await all_alerts(container))
    for d in (500, 560, 620, 900):  # stays delayed, delay grows → updated in place, no spam
        await push(container, b05(delay_s=d))
    assert len(await all_alerts(container)) == n
    mine = next(a for a in await by(container, AlertType.BUS_DELAYED) if a.student_id == "U-S0001")
    assert mine.body == "Bus B05 is running 15 minutes late." and mine.updated_at is not None
    await push(container, b05(delay_s=60))  # back on time → resolved
    assert all(not a.active for a in await by(container, AlertType.BUS_DELAYED))
    await push(container, b05(delay_s=420))  # late again → a new episode
    assert len(await by(container, AlertType.BUS_DELAYED, Role.ADMIN)) == 2


async def test_capacity_warning_transitions_use_feature8_occupancy(container):
    await push(container, b05(occupancy=39))  # 78 % of 50
    assert await by(container, AlertType.CAPACITY_WARNING) == []
    await push(container, b05(occupancy=42))  # 84 %
    (admin,) = await by(container, AlertType.CAPACITY_WARNING, Role.ADMIN)
    assert admin.body == "Bus B05 is 84% full with 8 seats remaining."
    assert (admin.payload["occupancy"], admin.payload["capacity"], admin.payload["available_seats"]) == (
        42,
        50,
        8,
    )
    n = len(await all_alerts(container))
    await push(container, b05(occupancy=45))
    assert len(await all_alerts(container)) == n  # stays above → no duplicate
    await push(container, b05(occupancy=20))
    assert all(not a.active for a in await by(container, AlertType.CAPACITY_WARNING))
    await push(container, b05(occupancy=41))
    assert len(await by(container, AlertType.CAPACITY_WARNING, Role.ADMIN)) == 2
    # unrelated buses never notify B05's students
    other = make_state("R1", 2_000, bus="B01").model_copy(update={"occupancy": 49})
    await push(container, other)
    b01_students = [
        a for a in await by(container, AlertType.CAPACITY_WARNING, Role.STUDENT) if a.bus_id == "B01"
    ]
    assigned_b01 = {a.id for a in await container.repos.student_assignments.for_bus("B01")}
    assert {a.student_id for a in b01_students} <= assigned_b01


async def test_new_trip_closes_the_previous_trips_episode(container):
    await push(container, b05(delay_s=480, trip="T-A"))
    await push(container, b05(delay_s=480, trip="T-B"))
    admin = await by(container, AlertType.BUS_DELAYED, Role.ADMIN)
    assert [(a.trip_id, a.active) for a in admin] == [("T-A", False), ("T-B", True)]


async def test_completed_trip_resolves_bus_alerts(container):
    await push(container, b05(delay_s=480, occupancy=45))
    await push(container, b05(delay_s=480, occupancy=45, status=BusStatus.COMPLETED))
    assert not [a for a in await all_alerts(container) if a.active]


# ================================================== student sweep triggers (fakes of F7/F9 output)


def recovery_result(
    *,
    eta_min=None,
    eta_status="predicted",
    decision="YES",
    trip="T-R3",
    variant="R3",
    bus_status=BusStatus.EN_ROUTE,
    recommended=None,
    student="U-S0001",
    ts=T0,
):
    p = None if eta_status is None else pred(eta_min, status=eta_status)
    return SimpleNamespace(
        commute=SimpleNamespace(
            assignment=SimpleNamespace(
                assignment=SimpleNamespace(id=student),
                direction=SimpleNamespace(variant_id="R3"),
                bus=SimpleNamespace(id="B05"),
                boarding_stop=SimpleNamespace(id="S27", name="Sholinganallur Junction"),
                route=SimpleNamespace(id="R3"),
            ),
            my_bus=SimpleNamespace(
                state=SimpleNamespace(variant_id=variant, trip_id=trip, status=bus_status)
            ),
            prediction=p,
            result=SimpleNamespace(decision=decision, reason="(Feature 7 reason)"),
        ),
        recovery=SimpleNamespace(
            status="recovery_available" if recommended else "not_needed",
            trigger="likely_to_miss" if recommended else None,
            recommended=recommended,
        ),
        computed_at=ts,
    )


def option(bus="B12", reason="Bus B12 serves your stop and gives you a 5-minute safety buffer."):
    return SimpleNamespace(
        candidate=SimpleNamespace(
            option=SimpleNamespace(
                sb=SimpleNamespace(
                    bus=SimpleNamespace(id=bus, capacity=50), state=SimpleNamespace(occupancy=24)
                ),
                prediction=pred(9),
            ),
            spare_minutes=5,
        ),
        available_seats=26,
        occupancy_percentage=48,
        reason=reason,
    )


async def student_alerts(container, type_):
    return [a for a in await by(container, type_) if a.student_id == "U-S0001"]


async def test_bus_approaching(container):
    s = svc(container)
    await s.evaluate_student(recovery_result(eta_min=12))  # outside the 5-min window
    assert await student_alerts(container, AlertType.BUS_APPROACHING) == []
    await s.evaluate_student(recovery_result(eta_min=3))
    (a,) = await student_alerts(container, AlertType.BUS_APPROACHING)
    assert a.body == "Bus B05 reaches your stop (Sholinganallur Junction) in 3 minutes."
    assert (a.bus_id, a.trip_id, a.student_id) == ("B05", "T-R3", "U-S0001")
    for m in (2, 1, 0):
        await s.evaluate_student(recovery_result(eta_min=m))
    await s.evaluate_student(recovery_result(eta_min=0, eta_status="at_stop"))
    assert len(await student_alerts(container, AlertType.BUS_APPROACHING)) == 1  # no duplicate
    await s.evaluate_student(recovery_result(eta_status="passed"))
    (a,) = await student_alerts(container, AlertType.BUS_APPROACHING)
    assert a.active is False  # bus passed → resolved, record kept
    await s.evaluate_student(recovery_result(eta_min=3))  # same trip: never again
    assert len(await student_alerts(container, AlertType.BUS_APPROACHING)) == 1
    await s.evaluate_student(recovery_result(eta_min=3, trip="T-NEXT"))  # next trip → new
    assert len(await student_alerts(container, AlertType.BUS_APPROACHING)) == 2


async def test_missed_bus(container):
    s = svc(container)
    for d in ("YES", "RISK"):
        await s.evaluate_student(recovery_result(eta_min=8, decision=d))
    assert await student_alerts(container, AlertType.MISSED_BUS) == []
    for _ in range(4):  # the bus passed the stop: its trip has started
        await s.evaluate_student(recovery_result(eta_status="passed", decision="MISSED"), trip_started=True)
    (a,) = await student_alerts(container, AlertType.MISSED_BUS)
    assert a.body == "You missed your assigned bus B05." and a.bus_id == "B05"
    await s.evaluate_student(
        recovery_result(eta_status="passed", decision="MISSED", trip="T-NEXT"), trip_started=True
    )
    assert len(await student_alerts(container, AlertType.MISSED_BUS)) == 2  # a later trip


async def test_missed_requires_a_started_trip(container):
    """A MISSED decision for a trip that has not started (e.g. a driver-controlled bus still
    waiting for Start Trip, or an outdated state after a reset) raises nothing; an alert
    already open for that trip is resolved."""
    s = svc(container)
    await s.evaluate_student(recovery_result(eta_status="passed", decision="MISSED"), trip_started=False)
    assert await student_alerts(container, AlertType.MISSED_BUS) == []
    # no explicit flag: looked up in the trip store (T-R3 doesn't exist → not started)
    await s.evaluate_student(recovery_result(eta_status="passed", decision="MISSED"))
    assert await student_alerts(container, AlertType.MISSED_BUS) == []
    await s.evaluate_student(recovery_result(eta_status="passed", decision="MISSED"), trip_started=True)
    (a,) = await student_alerts(container, AlertType.MISSED_BUS)
    await s.evaluate_student(recovery_result(eta_min=8, decision="YES"), trip_started=False)
    assert (await container.repos.alerts.get(a.id)).active is False


async def test_missed_bus_mentions_recovery_and_skips_boarded_students(container):
    s = svc(container)
    await s.evaluate_student(
        recovery_result(eta_status="passed", decision="MISSED", recommended=option()), trip_started=True
    )
    (a,) = await student_alerts(container, AlertType.MISSED_BUS)
    assert a.body == "You missed your assigned bus B05. An alternative bus is available."
    await s.evaluate_student(
        recovery_result(eta_status="passed", decision="MISSED", trip="T-2", student="U-S0002"),
        boarded=True,
        trip_started=True,
    )
    assert not [x for x in await by(container, AlertType.MISSED_BUS) if x.student_id == "U-S0002"]


async def test_missed_is_not_raised_when_the_bus_runs_another_direction(container):
    s = svc(container)
    await s.evaluate_student(
        recovery_result(eta_status=None, decision="MISSED", variant="R3-E", trip="T-EVE")
    )
    assert await student_alerts(container, AlertType.MISSED_BUS) == []


async def test_alternative_bus_available(container):
    s = svc(container)
    await s.evaluate_student(recovery_result(eta_min=8))
    assert await student_alerts(container, AlertType.ALTERNATIVE_BUS_AVAILABLE) == []
    for _ in range(3):
        await s.evaluate_student(recovery_result(eta_min=4, decision="RISK", recommended=option()))
    (a,) = await student_alerts(container, AlertType.ALTERNATIVE_BUS_AVAILABLE)
    assert a.body == "Bus B12 serves your stop and gives you a 5-minute safety buffer."  # Feature 9's reason
    assert a.bus_id == "B12" and a.payload["available_seats"] == 26 and a.payload["eta_minutes"] == 9
    # the recommendation changes → the SAME alert is updated, not a second one
    await s.evaluate_student(
        recovery_result(
            eta_min=4, decision="RISK", recommended=option("B06", "Bus B06 is the next catchable bus.")
        )
    )
    (a,) = await student_alerts(container, AlertType.ALTERNATIVE_BUS_AVAILABLE)
    assert a.bus_id == "B06" and a.body == "Bus B06 is the next catchable bus." and a.updated_at is not None
    await s.evaluate_student(recovery_result(eta_min=8))  # recovery gone → resolved
    (a,) = await student_alerts(container, AlertType.ALTERNATIVE_BUS_AVAILABLE)
    assert a.active is False


# =========================================================================== simulator end-to-end


async def _sim(container):
    from app.main import attach_simulator

    attach_simulator(container)
    await container.simulator.reset()
    return container.alert_monitor()


async def test_simulated_morning_alerts_without_duplicates(container):
    mon = await _sim(container)
    for _ in range(40):  # 40 sim minutes, a sweep every sim minute
        await _advance(container, 60)
        await mon.sweep()
    alerts = await all_alerts(container)
    active_series = [a.dedup_key for a in alerts if a.active]
    assert len(active_series) == len(set(active_series))  # at most one active per series
    mine = {a.type for a in alerts if a.student_id == "U-S0001"}
    assert {AlertType.BUS_APPROACHING, AlertType.MISSED_BUS, AlertType.ALTERNATIVE_BUS_AVAILABLE} <= mine
    for t in (AlertType.BUS_APPROACHING, AlertType.MISSED_BUS):  # once per trip
        assert len([a for a in alerts if a.student_id == "U-S0001" and a.type is t]) == 1
    n = len(alerts)
    for _ in range(5):  # polling-like repetition without time passing
        await mon.sweep()
    assert len(await all_alerts(container)) == n
    await container.simulator.reset()  # a replayed day starts clean for simulated buses
    assert await all_alerts(container) == []
    await container.simulator.shutdown()


async def test_route_deviation_alerts_go_through_the_central_service(container):
    mon = await _sim(container)
    await _advance(container, 10 * 60)
    container.simulator.set_route_deviation("major", "B05")
    await _advance(container, 60)
    await mon.sweep()
    dev = await by(container, AlertType.ROUTE_DEVIATION)
    admin = [a for a in dev if a.audience.role is Role.ADMIN]
    students = [a for a in dev if a.audience.role is Role.STUDENT]
    assert len(admin) == 1 and admin[0].severity is Severity.CRITICAL
    assert admin[0].body.startswith("BUS B05 is ") and admin[0].payload["kind"] == "route_deviation"
    assert "U-S0001" in {a.student_id for a in students}
    assert any(a.body.startswith("Your bus B05 is currently ") for a in students)
    container.simulator.set_route_deviation("normal", "B05")
    await _advance(container, 30)
    assert not [a for a in await by(container, AlertType.ROUTE_DEVIATION) if a.active]
    await container.simulator.shutdown()
