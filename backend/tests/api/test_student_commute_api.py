"""Feature 16 — /students/me/commute and /students/me/history (B07 driver-controlled).

Everything is read back through the API from authoritative records; test setup only uses
the real flows (driver start/stop, simulated QR scans, simulator reset) except where noted.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.config import Settings
from app.main import create_app
from app.models import BoardingEvent, Trip, User
from app.models.common import AlertType, BoardingSource, BoardingType, Role, StopProximity, TripStatus
from app.services.student_commute_service import commute_phase, history_outcome
from tests.conftest import SEED, SERVICE_DATE, advance, login
from tests.wsclient import WsTestClient, of_type

DRIVER = "driver07@campusride.demo"
ADMIN = "admin1@campusride.demo"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        seed=SEED,
        mock_token_secret="test-secret",
        sim_driver_controlled_buses="B07",
        ws_flush_interval_s=3600,
    )


async def _riders(container) -> list[tuple[int, str, str]]:
    """B07's assigned students as (stop seq, student id, email), ordered along the route."""
    out = []
    for a in await container.repos.student_assignments.for_bus("B07"):
        route = await container.repos.routes.get("R4")
        seq = route.variant(a.assigned_route_direction_id).stop(a.boarding_stop_id).seq
        out.append((seq, a.id, (await container.repos.users.get(a.id)).email))
    return sorted(out)


async def _get(client, path, headers, **params):
    r = await client.get(path, headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ============================================================================ pure rules


def test_commute_phase_rules():
    trip = Trip(
        _id="T", route_id="R", direction="to_campus", variant_id="R", bus_id="B", service_date=SERVICE_DATE,
        scheduled_start="2026-10-05T01:45:00Z",
    )  # fmt: skip
    active = trip.model_copy(update={"status": TripStatus.ACTIVE})
    done = trip.model_copy(update={"status": TripStatus.COMPLETED})
    kw = {
        "assigned": True,
        "on_commute": True,
        "boarded": False,
        "decision": "YES",
        "recovery_available": False,
    }
    assert commute_phase(**(kw | {"assigned": False}), trip=None, proximity=None)[0] == "unassigned"
    assert commute_phase(**(kw | {"on_commute": False}), trip=active, proximity=None)[0] == "no_trip"
    assert commute_phase(**kw, trip=trip, proximity=StopProximity.FAR_FROM_STOP)[0] == "waiting"
    assert commute_phase(**kw, trip=active, proximity=StopProximity.APPROACHING_STOP)[0] == "approaching"
    assert commute_phase(**kw, trip=active, proximity=StopProximity.AT_STOP)[0] == "at_stop"
    assert commute_phase(**(kw | {"boarded": True}), trip=active, proximity=None)[0] == "on_board"
    assert commute_phase(**(kw | {"boarded": True}), trip=done, proximity=None)[0] == "completed"
    missed = kw | {"decision": "MISSED"}
    assert commute_phase(**missed, trip=active, proximity=None)[0] == "missed"
    assert commute_phase(**(missed | {"recovery_available": True}), trip=active, proximity=None)[0] == (
        "recovery_available"
    )
    # a MISSED decision for a trip that has NOT started (driver hasn't pressed Start) is not "missed"
    assert commute_phase(**missed, trip=trip, proximity=None)[0] == "waiting"


def test_history_outcome_rules():
    base = Trip(
        _id="T", route_id="R", direction="to_campus", variant_id="R", bus_id="B", service_date=SERVICE_DATE,
        scheduled_start="2026-10-05T01:45:00Z", status=TripStatus.COMPLETED,
    )  # fmt: skip
    b = BoardingEvent(
        _id="x", trip_id="T", bus_id="B", stop_id="S", student_id="U", ts="2026-10-05T01:50:00Z",
        type=BoardingType.BOARD, source=BoardingSource.QR,
    )  # fmt: skip

    class A:
        def __init__(self, reason):
            self.payload = {"reason": reason}

    from app.services.commute_decision_service import REASON

    assert history_outcome(base, b, None) == "boarded"
    assert history_outcome(base.model_copy(update={"status": TripStatus.ACTIVE}), None, None) == "in_progress"
    assert history_outcome(base, None, A(REASON["passed"])) == "missed"
    stopped = base.model_copy(update={"end_reason": "driver_stop"})
    assert history_outcome(stopped, None, A(REASON["completed"])) == "ended_early"
    assert history_outcome(stopped, None, A(REASON["passed"])) == "missed"  # bus passed before the stop
    assert history_outcome(base, None, None) == "no_boarding_recorded"


# ============================================================================ today's commute


async def test_commute_requires_a_student_and_is_self_scoped(live_client, student_headers):
    client, container = live_client
    assert (await client.get("/students/me/commute")).status_code == 401
    for email in (DRIVER, ADMIN):
        h = await login(client, email)
        assert (await client.get("/students/me/commute", headers=h)).status_code == 403
        assert (await client.get("/students/me/history", headers=h)).status_code == 403
    mine = await _get(client, "/students/me/commute", student_headers, student_id="U-S0002")  # ignored
    assert mine["student_id"] == "U-S0001"
    await container.repos.users.upsert(
        User(id="U-S9999", role=Role.STUDENT, name="New Student", email="new@campusride.demo")
    )
    fresh = await _get(client, "/students/me/commute", await login(client, "new@campusride.demo"))
    assert (fresh["status"], fresh["phase"], fresh["assignment"], fresh["bus"]) == (
        "unassigned", "unassigned", None, None,
    )  # fmt: skip


async def test_commute_reuses_the_authoritative_answers(live_client, student_headers):
    client, container = live_client
    await advance(container, 6 * 60)
    c = await _get(client, "/students/me/commute", student_headers)
    assert c["assignment"] == (await _get(client, "/students/me/assignment", student_headers))["assignment"]
    bus = {b["id"]: b for b in await _get(client, "/buses", student_headers)}[c["assignment"]["bus"]["id"]]
    assert c["bus"] == bus  # the GET /buses item
    for key, path in (
        ("decision", "/students/me/commute-decision"),
        ("recovery", "/students/me/recovery-options"),
        ("boarding", "/students/me/boarding"),
    ):
        other = await _get(client, path, student_headers)
        drop = {"computed_at"}
        assert {k: v for k, v in c[key].items() if k not in drop} == {
            k: v for k, v in other.items() if k not in drop
        }, key
    assert c["decision"]["eta"] is not None  # Feature 5 ETA embedded in the decision
    assert c["trip"]["trip_id"] == bus["live"]["trip_id"]
    assert c["phase"] in ("waiting", "approaching", "at_stop", "missed", "recovery_available", "no_trip")


async def test_driver_controlled_waiting_is_not_missed_and_not_history(live_client):
    client, container = live_client
    (_, _, email) = (await _riders(container))[0]
    h = await login(client, email)
    for _ in range(6):  # an hour past the scheduled departure, driver hasn't pressed Start
        await advance(container, 10 * 60)
        await container.alert_monitor().sweep()
        c = await _get(client, "/students/me/commute", h)
        assert (
            c["phase"] in ("waiting", "at_stop") and c["trip"]["status"] == "scheduled"
        )  # bus waits at stop 1
        assert c["decision"]["decision"] != "MISSED"
    assert (await _get(client, "/students/me/history", h))["entries"] == []
    missed = [
        a for a in await container.repos.alerts.list() if a.type is AlertType.MISSED_BUS and a.bus_id == "B07"
    ]
    assert missed == []


# ============================================================================ boarding + full trip + history


async def test_full_commute_board_complete_and_history(live_client):
    client, container = live_client
    riders = await _riders(container)
    _seq, sid, email = riders[-1]  # the last stop before campus: time to approach and board
    h = await login(client, email)
    d = await login(client, DRIVER)
    trip_id = (await client.post("/driver/trip/start", headers=d)).json()["trip"]["id"]
    phases = []
    me = None
    for _ in range(240):  # up to 2 h of simulated time in 30 s steps
        await advance(container, 30)
        c = await _get(client, "/students/me/commute", h)
        phases.append(c["phase"])
        if c["boarding"]["ready"]:
            me = c["boarding"]
            break
    assert me is not None, phases
    assert "waiting" in phases and c["trip"]["status"] == "active" and c["trip"]["trip_id"] == trip_id
    before = c["bus"]["live"]["occupancy"]
    scan = {
        "student_id": sid,
        "bus_id": "B07",
        "trip_id": trip_id,
        "timestamp": container.clock.now().isoformat(),
    }
    forged = scan | {"student_id": riders[0][1]}
    assert (
        await client.post("/boarding/scan", json=forged, headers=h)
    ).status_code == 403  # identity from auth
    r = await client.post("/boarding/scan", json=scan, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "boarded"
    again = await client.post("/boarding/scan", json=scan, headers=h)
    assert again.status_code == 200 and again.json()["status"] == "already_boarded"  # no duplicate
    c = await _get(client, "/students/me/commute", h)
    assert c["phase"] == "on_board" and c["boarding"]["boarded"]["trip_id"] == trip_id
    assert c["bus"]["live"]["occupancy"] == min(50, before + 1)  # Feature 8 occupancy
    assert len(await container.repos.boarding_events.for_trip(trip_id)) == 1

    await advance(container, 90 * 60)  # reaches campus → completed by tracking
    c = await _get(client, "/students/me/commute", h)
    assert c["phase"] == "completed" and c["trip"]["status"] == "completed"
    assert c["trip"]["end_reason"] == "terminal"
    (entry,) = (await _get(client, "/students/me/history", h))["entries"]
    assert (entry["trip_id"], entry["outcome"], entry["boarded"], entry["trip_status"]) == (
        trip_id, "boarded", True, "completed",
    )  # fmt: skip
    assert entry["end_reason"] == "terminal" and entry["boarding_time"] and entry["scanner"] == "simulated"
    assert entry["bus_id"] == "B07" and entry["route_name"] and entry["direction_label"]
    assert entry["boarding_stop"]["id"] == me["boarding_stop"]["id"]
    # another student never sees it
    other = await login(client, riders[0][2])
    assert all(e["boarded"] is False for e in (await _get(client, "/students/me/history", other))["entries"])


async def test_early_stop_and_missed_are_told_apart(live_client):
    client, container = live_client
    riders = await _riders(container)
    d = await login(client, DRIVER)
    trip_id = (await client.post("/driver/trip/start", headers=d)).json()["trip"]["id"]
    await advance(container, 4 * 60)  # the bus has passed the first stops
    await container.alert_monitor().sweep()
    assert (await client.post("/driver/trip/stop", headers=d)).status_code == 200
    await advance(container, 30)
    await container.alert_monitor().sweep()
    trip = await container.repos.trips.get(trip_id)
    assert trip.status is TripStatus.COMPLETED and trip.end_reason == "driver_stop"
    outcomes = {}
    for _seq, _sid, email in riders:
        (e,) = (await _get(client, "/students/me/history", await login(client, email)))["entries"]
        assert e["trip_id"] == trip_id and e["end_reason"] == "driver_stop"
        outcomes[_seq] = e["outcome"]
    assert outcomes[riders[0][0]] == "missed"  # the bus passed this stop before the driver stopped
    assert outcomes[riders[-1][0]] == "ended_early"  # never reached this stop
    assert set(outcomes.values()) <= {"missed", "ended_early"}


async def test_reset_replays_today_without_duplicates_and_keeps_other_days(live_client):
    client, container = live_client
    (_, sid, email) = (await _riders(container))[-1]
    h, admin = await login(client, email), await login(client, ADMIN)
    # an earlier service date for B07, created through the repositories (a previous day's records)
    today = await container.repos.trips.get((await container.repos.bus_states.get("B07")).trip_id)
    prev_date = SERVICE_DATE - timedelta(days=1)
    past = today.model_copy(
        update={
            "id": today.id.replace(SERVICE_DATE.strftime("%Y%m%d"), prev_date.strftime("%Y%m%d")),
            "service_date": prev_date,
            "scheduled_start": today.scheduled_start - timedelta(days=1),
            "status": TripStatus.COMPLETED,
            "actual_start": today.scheduled_start - timedelta(days=1),
            "actual_end": today.scheduled_start - timedelta(days=1, minutes=-50),
            "end_reason": "terminal",
        }
    )
    await container.repos.trips.upsert(past)
    await container.repos.boarding_events.insert_once(
        BoardingEvent(
            _id=f"BRD-{past.id}-{sid}", trip_id=past.id, bus_id="B07", stop_id="S20", student_id=sid,
            ts=past.actual_start + timedelta(minutes=20), type=BoardingType.BOARD, source=BoardingSource.QR,
            scanner="simulated",
        )
    )  # fmt: skip
    d = await login(client, DRIVER)
    await client.post("/driver/trip/start", headers=d)
    await advance(container, 3 * 60)
    await client.post("/driver/trip/stop", headers=d)
    hist = (await _get(client, "/students/me/history", h))["entries"]
    assert [e["trip_id"] for e in hist] == [today.id, past.id]  # newest first, deterministic
    assert (await client.post("/sim/reset", headers=admin)).status_code == 200
    again = (await _get(client, "/students/me/history", h))["entries"]
    assert [e["trip_id"] for e in again] == [past.id]  # today replays (scheduled again): no duplicate
    assert again[0]["outcome"] == "boarded"  # the earlier day's boarding survives the reset
    assert await container.repos.boarding_events.for_student_trip(sid, past.id) is not None


# ============================================================================ realtime


async def test_boarding_and_trip_events_reach_the_right_audiences(live_client):
    client, container = live_client
    riders = await _riders(container)
    _seq, sid, email = riders[-1]
    h = await login(client, email)
    app = create_app(container=container)
    socks = {}
    try:
        for name, headers in (
            ("rider", h),
            ("other", await login(client, riders[0][2])),
            ("admin", await login(client, ADMIN)),
            ("driver", await login(client, DRIVER)),
        ):
            s = await WsTestClient(app).connect()
            await s.auth(headers)
            socks[name] = s
        d = await login(client, DRIVER)
        trip_id = (await client.post("/driver/trip/start", headers=d)).json()["trip"]["id"]
        assert of_type(await socks["rider"].drain(), "trip.started")[0]["data"]["trip_id"] == trip_id
        for _ in range(240):
            await advance(container, 30)
            b = await _get(client, "/students/me/boarding", h)
            if b["ready"]:
                break
        for s in socks.values():
            await s.drain()
        scan = {
            "student_id": sid,
            "bus_id": "B07",
            "trip_id": trip_id,
            "timestamp": container.clock.now().isoformat(),
        }
        assert (await client.post("/boarding/scan", json=scan, headers=h)).status_code == 200
        got = {k: of_type(await s.drain(), "boarding.updated") for k, s in socks.items()}
        assert got["rider"][0]["data"]["student_id"] == sid
        assert got["admin"][0]["data"]["student_id"] == sid
        assert got["driver"][0]["data"]["student_id"] is None
        assert got["other"] == []  # another student's boarding never leaks
        assert (await client.post("/driver/trip/stop", headers=d)).status_code == 200
        assert of_type(await socks["rider"].drain(), "trip.completed")[0]["data"]["trip_id"] == trip_id
    finally:
        for s in socks.values():
            await s.close()
        await container.realtime().shutdown()
