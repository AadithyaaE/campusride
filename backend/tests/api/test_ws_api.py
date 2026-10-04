"""Feature 14 — /api/v1/ws: auth, audiences, event flow from the EXISTING event bus, cleanup.

Bus updates are coalesced and pushed by ``RealtimeHub.flush`` (a background loop in the
app); tests call ``flush()`` directly for determinism.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.core.config import Settings
from app.main import create_app
from app.models.common import AlertType, BusStatus, TripStatus
from app.models.events import BusStateUpdated
from app.realtime.manager import Audience, ConnectionManager
from app.services.alert_service import ADMINS, AlertSpec, Recipient
from tests.conftest import SEED, advance, login
from tests.wsclient import WsTestClient, of_type, types

ADMIN = "admin1@campusride.demo"
DRIVER07 = "driver07@campusride.demo"
DRIVER05 = "driver05@campusride.demo"


@pytest.fixture
def settings() -> Settings:  # module override: B07 driver-controlled, manual flushes
    return Settings(
        _env_file=None,
        app_env="test",
        seed=SEED,
        mock_token_secret="test-secret",
        sim_driver_controlled_buses="B07",
        ws_flush_interval_s=3600,
        ws_overview_min_interval_s=0,
        ws_auth_timeout_s=0.5,
    )


@pytest.fixture
async def ws(live_client):
    """Factory: open authenticated sockets on the SAME container as the REST client."""
    _, container = live_client
    app = create_app(container=container)
    opened: list[WsTestClient] = []

    async def open_(headers: dict[str, str] | None = None) -> WsTestClient:
        sock = await WsTestClient(app).connect()
        opened.append(sock)
        if headers is not None:
            sock.hello = await sock.auth(headers)
        return sock

    yield open_
    for s in opened:
        try:
            await s.close()
        except Exception:
            pass
    await container.realtime().shutdown()


async def _flush(container) -> None:
    await container.realtime().flush()


async def _student_of(client, container, bus_id: str, ready: bool = True):
    """(user id, headers) of an assigned student of ``bus_id`` (whose stop is ahead if ``ready``)."""
    for a in sorted(await container.repos.student_assignments.for_bus(bus_id), key=lambda a: a.id):
        user = await container.repos.users.get(a.id)
        headers = await login(client, user.email)
        if not ready:
            return a.id, headers
        me = (await client.get("/students/me/boarding", headers=headers)).json()
        if me["ready"]:
            return a.id, headers
    pytest.fail(f"no boardable student on {bus_id}")


# ----------------------------------------------------------------------------- authentication


async def test_authenticated_hello_per_role(live_client, ws, student_headers):
    client, container = live_client
    admin = await ws(await login(client, ADMIN))
    student = await ws(student_headers)
    driver = await ws(await login(client, DRIVER07))
    assert admin.hello["data"]["role"] == "admin" and admin.hello["data"]["bus_id"] is None
    assert student.hello["data"] == {
        "user_id": "U-S0001",
        "role": "student",
        "bus_id": None,
        "heartbeat_s": 20.0,
        "flush_interval_s": 3600.0,
    }
    assert driver.hello["data"]["role"] == "driver" and driver.hello["data"]["bus_id"] == "B07"
    assert len(container.realtime().manager) == 3
    env = admin.hello
    assert set(env) == {"id", "type", "seq", "ts", "sent_at", "scope", "data"}
    assert env["id"].startswith("evt-") and env["scope"] == "user"


async def test_invalid_authentication_is_refused(ws, live_client):
    _, container = live_client
    bad = await ws()
    await bad.send({"type": "auth", "token": "mock.forged.signature"})
    assert await bad.wait_closed() == 4401
    wrong = await ws()
    await wrong.send({"type": "subscribe", "topic": "fleet"})  # not an auth message
    assert await wrong.wait_closed() == 4401
    junk = await ws()
    await junk._in.put({"type": "websocket.receive", "text": "not json"})
    assert await junk.wait_closed() == 4401
    silent = await ws()  # never authenticates
    assert await silent.wait_closed(wait_s=3) == 4408
    assert len(container.realtime().manager) == 0


async def test_disconnect_cleans_up(live_client, ws, student_headers):
    _, container = live_client
    s = await ws(student_headers)
    assert len(container.realtime().manager) == 1
    await s.close()
    assert len(container.realtime().manager) == 0
    # pushing to nobody is a no-op
    assert (
        container.realtime()._send("sim.reset", {}, Audience.everyone(), "system", container.clock.now()) == 0
    )


# ----------------------------------------------------------------------------- THE end-to-end flow


async def test_driver_admin_student_end_to_end(live_client, ws, student_headers):
    """Driver → simulator → telemetry → tracking → EventBus → WebSocket → all three apps."""
    client, container = live_client
    hub = container.realtime()
    d07_headers = await login(client, DRIVER07)
    admin = await ws(await login(client, ADMIN))
    student = await ws(student_headers)  # U-S0001 (assigned to another bus)
    rider_id, rider_headers = await _student_of(client, container, "B07", ready=False)
    rider = await ws(rider_headers)
    driver07 = await ws(d07_headers)
    driver05 = await ws(await login(client, DRIVER05))
    await _flush(container)  # initial fleet push (prepared buses)
    for s in (admin, student, rider, driver07, driver05):
        await s.drain()

    # 1–5. driver starts → ACTIVE → trip.started immediately (no flush needed)
    r = await client.post("/driver/trip/start", headers=d07_headers)
    assert r.status_code == 200, r.text
    trip_id = r.json()["trip"]["id"]
    assert (await container.repos.trips.get(trip_id)).status is TripStatus.ACTIVE
    for s in (admin, student, driver07):
        started = of_type(await s.drain(), "trip.started")
        assert [m["data"] for m in started] == [
            {"trip_id": trip_id, "bus_id": "B07", "route_id": "R4", "route_direction_id": "R4"}
        ]
    assert of_type(await driver05.drain(), "trip.started") == []  # not driver 05's bus

    # 6–10. simulator telemetry → tracking → BusState → coalesced push
    await advance(container, 3 * 60)
    await _flush(container)
    state = await container.repos.bus_states.get("B07")
    adm, stu, d07, d05 = [await s.drain() for s in (admin, student, driver07, driver05)]
    for msgs in (adm, stu, d07):
        b07 = [m for m in of_type(msgs, "bus.state.updated") if m["data"]["bus"]["id"] == "B07"]
        assert len(b07) == 1  # coalesced: 36 fixes → one push
        live = b07[0]["data"]["bus"]["live"]
        assert live["location"]["coordinates"] == list(state.location.coordinates)  # = GET /buses
        assert live["trip_id"] == trip_id and live["status"] in ("en_route", "dwelling")
    rest = {b["id"]: b for b in (await client.get("/buses", headers=student_headers)).json()}["B07"]
    pushed = next(m for m in of_type(stu, "bus.state.updated") if m["data"]["bus"]["id"] == "B07")
    assert pushed["data"]["bus"] == rest  # the exact REST DTO, nothing recomputed
    # admin-only row (Feature 13) and ETA (Feature 5)
    assert any(m["data"]["bus"]["bus_id"] == "B07" for m in of_type(adm, "fleet.bus.updated"))
    assert of_type(stu, "fleet.bus.updated") == [] and of_type(d07, "fleet.bus.updated") == []
    eta = next(m for m in of_type(stu, "eta.updated") if m["data"]["bus_id"] == "B07")["data"]
    fleet_rest = (await client.get("/admin/fleet", headers=await login(client, ADMIN))).json()["buses"]
    row = next(b for b in fleet_rest if b["bus_id"] == "B07")
    assert eta["eta_minutes"] == row["eta_next_stop_min"] is not None  # the Feature 5 value
    assert eta["next_stop"]["id"] == state.next_stop_id
    # driver's private dashboard → only driver 07
    dash = of_type(d07, "driver.state.updated")
    assert dash and dash[-1]["data"]["trip_state"] == "ACTIVE" and dash[-1]["data"]["bus"]["id"] == "B07"
    assert dash[-1]["data"]["live"]["speed_kmh"] == round(state.speed_mps * 3.6)
    assert not any(m["data"].get("bus", {}).get("id") == "B07" for m in of_type(d05, "bus.state.updated"))
    assert of_type(d05, "driver.state.updated") == [] or all(
        m["data"]["bus"]["id"] == "B05" for m in of_type(d05, "driver.state.updated")
    )
    assert of_type(stu, "driver.state.updated") == []

    # 11–13. QR boarding → occupancy.updated (+ boarding.updated, private to the rider/admin)
    before = state.occupancy
    ready_id, ready_headers = await _student_of(client, container, "B07")  # stop still ahead
    if ready_id != rider_id:
        rider_id, rider_headers, rider = ready_id, ready_headers, await ws(ready_headers)
    me = (await client.get("/students/me/boarding", headers=rider_headers)).json()
    scan = {k: me[k] for k in ("student_id", "bus_id", "trip_id")} | {
        "timestamp": container.clock.now().isoformat()
    }
    assert (await client.post("/boarding/scan", json=scan, headers=rider_headers)).status_code == 200
    adm, stu, rid, d07 = [await s.drain() for s in (admin, student, rider, driver07)]
    assert of_type(adm, "boarding.updated")[0]["data"]["student_id"] == rider_id
    assert of_type(rid, "boarding.updated")[0]["data"]["student_id"] == rider_id
    assert of_type(d07, "boarding.updated")[0]["data"]["student_id"] is None  # driver: count only
    assert of_type(stu, "boarding.updated") == []  # another student's boarding never leaks
    await _flush(container)
    adm, stu, d07 = [await s.drain() for s in (admin, student, driver07)]
    for msgs in (adm, stu, d07):
        occ = [m["data"] for m in of_type(msgs, "occupancy.updated") if m["data"]["bus_id"] == "B07"]
        assert occ and occ[-1]["passengers"] == min(50, before + 1) and occ[-1]["boarded_count"] == 1
        assert occ[-1]["capacity"] == 50
    assert of_type(d07, "driver.state.updated")[-1]["data"]["live"]["occupancy"] == occ[-1]["passengers"]

    # 14–17. route deviation (Feature 10) → route.deviation + alert.created (Feature 11)
    await client.post(
        "/sim/route-deviation", json={"mode": "major", "bus_id": "B07"}, headers=await login(client, ADMIN)
    )
    await advance(container, 30)
    await _flush(container)
    adm, stu, rid, d07, d05 = [await s.drain() for s in (admin, student, rider, driver07, driver05)]
    dev = [m["data"] for m in of_type(adm, "route.deviation") if m["data"]["bus_id"] == "B07"]
    assert dev and dev[0]["route_status"] == "MAJOR_DEVIATION" and dev[0]["deviation_distance_m"] >= 150
    assert of_type(d07, "route.deviation")
    created = [m for m in of_type(adm, "alert.created") if m["data"]["type"] == "ROUTE_DEVIATION"]
    assert created and created[0]["data"]["recipient"] == "admin" and created[0]["scope"] == "admin"
    # the admin alert is never sent to students or drivers; the assigned rider gets their OWN alert
    for msgs in (stu, d07, d05):
        assert all(m["data"]["recipient"] != "admin" for m in of_type(msgs, "alert.created"))
    own = of_type(rid, "alert.created")
    assert own and all(m["data"]["student_id"] == rider_id for m in own)
    assert all(m["data"].get("student_id") != rider_id for m in of_type(stu, "alert.created"))
    assert of_type(d05, "route.deviation") == []

    # back to normal → route.deviation (leaving) + alert.resolved
    await client.post(
        "/sim/route-deviation", json={"mode": "normal", "bus_id": "B07"}, headers=await login(client, ADMIN)
    )
    await advance(container, 30)
    await _flush(container)
    adm = await admin.drain()
    back = [m["data"] for m in of_type(adm, "route.deviation") if m["data"]["bus_id"] == "B07"]
    assert back and back[-1]["route_status"] == "NORMAL" and back[-1]["previous_status"] == "MAJOR_DEVIATION"
    assert any(m["data"]["type"] == "ROUTE_DEVIATION" for m in of_type(adm, "alert.resolved"))

    # 18–20. driver stops → trip.completed immediately; final state on the next flush
    assert (await client.post("/driver/trip/stop", headers=d07_headers)).status_code == 200
    adm, stu, d07 = [await s.drain() for s in (admin, student, driver07)]
    for msgs in (adm, stu, d07):
        done = of_type(msgs, "trip.completed")
        assert [m["data"]["trip_id"] for m in done] == [trip_id]
    await _flush(container)
    adm, d07 = await admin.drain(), await driver07.drain()
    final = [m for m in of_type(adm, "fleet.bus.updated") if m["data"]["bus"]["bus_id"] == "B07"]
    assert final[-1]["data"]["bus"]["operational_status"] == "completed"
    assert of_type(adm, "admin.overview.updated")[-1]["data"]["trips_today"]["completed"] >= 1
    assert of_type(d07, "driver.state.updated")[-1]["data"]["trip_state"] in ("READY", "COMPLETED")
    # envelope order: seq strictly increasing per socket
    seqs = [m["seq"] for m in adm]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert hub.flushes >= 5


# ----------------------------------------------------------------------------- audiences


async def test_student_alerts_are_private_and_admin_alerts_shared(live_client, ws, student_headers):
    client, container = live_client
    other_headers = await login(client, "student002@campusride.demo")
    a1 = await ws(await login(client, ADMIN))
    a2 = await ws(await login(client, "admin2@campusride.demo"))
    s1, s2 = await ws(student_headers), await ws(other_headers)
    d07 = await ws(await login(client, DRIVER07))
    svc = container.alerts()
    now = container.clock.now()
    mine = await svc.create_alert(
        AlertSpec(
            AlertType.BUS_APPROACHING,
            Recipient("U-S0001"),
            "Bus B05 reaches your stop in 3 minutes.",
            now,
            "B05",
            "T1",
            "R3",
        )
    )
    fleet = await svc.create_alert(
        AlertSpec(AlertType.CAPACITY_WARNING, ADMINS, "Bus B07 is 88% full.", now, "B07", "T7", "R4")
    )
    m1, m2, ad1, ad2, dr = [await s.drain() for s in (s1, s2, a1, a2, d07)]
    assert [m["data"]["alert_id"] for m in of_type(m1, "alert.created")] == [mine.id]
    assert of_type(m2, "alert.created") == [] and of_type(dr, "alert.created") == []
    for msgs in (ad1, ad2):
        assert [m["data"]["alert_id"] for m in of_type(msgs, "alert.created")] == [fleet.id]
    # read: an admin alert's shared read flag → every admin; a student's → only them
    assert (
        await client.patch(f"/alerts/{fleet.id}/read", headers=await login(client, ADMIN))
    ).status_code == 200
    assert (await client.patch(f"/alerts/{mine.id}/read", headers=student_headers)).status_code == 200
    m1, m2, ad1, ad2 = [await s.drain() for s in (s1, s2, a1, a2)]
    for msgs in (ad1, ad2):
        assert [m["data"] for m in of_type(msgs, "alert.read")] == [{"alert_id": fleet.id, "read": True}]
    assert [m["data"]["alert_id"] for m in of_type(m1, "alert.read")] == [mine.id]
    assert of_type(m2, "alert.read") == []
    await svc.resolve_alert(mine.dedup_key, now + timedelta(minutes=1))
    assert of_type(await s1.drain(), "alert.resolved") and of_type(await s2.drain(), "alert.resolved") == []


async def test_drivers_only_get_their_own_bus(live_client, ws):
    client, container = live_client
    d05 = await ws(await login(client, DRIVER05))
    assert d05.hello["data"]["bus_id"] == "B05"
    await advance(container, 5 * 60)  # B05 runs on schedule, B07 waits
    await _flush(container)
    msgs = await d05.drain()
    buses = {m["data"]["bus"]["id"] for m in of_type(msgs, "bus.state.updated")}
    assert buses == {"B05"}
    assert {m["data"]["bus_id"] for m in of_type(msgs, "occupancy.updated")} <= {"B05"}
    assert of_type(msgs, "driver.state.updated")[-1]["data"]["bus"]["id"] == "B05"
    assert of_type(msgs, "fleet.bus.updated") == [] and of_type(msgs, "admin.overview.updated") == []


async def test_admin_gets_fleet_rows_and_overview(live_client, ws, student_headers):
    client, container = live_client
    admin = await ws(await login(client, ADMIN))
    student = await ws(student_headers)
    await advance(container, 5 * 60)
    await _flush(container)
    adm, stu = await admin.drain(), await student.drain()
    rows = {m["data"]["bus"]["bus_id"] for m in of_type(adm, "fleet.bus.updated")}
    assert len(rows) == 12  # every bus once (coalesced)
    rest = (await client.get("/admin/overview", headers=await login(client, ADMIN))).json()
    ov = of_type(adm, "admin.overview.updated")[-1]["data"]
    assert ov["active_trips"] == rest["active_trips"] and ov["total_buses"] == 12
    assert of_type(stu, "admin.overview.updated") == [] and of_type(stu, "fleet.bus.updated") == []
    assert len({m["data"]["bus"]["id"] for m in of_type(stu, "bus.state.updated")}) == 12


# ----------------------------------------------------------------------------- change detection / ordering


async def test_coalescing_change_detection_and_ordering(live_client, ws):
    client, container = live_client
    hub = container.realtime()
    admin = await ws(await login(client, ADMIN))
    await advance(container, 5 * 60)
    await _flush(container)
    await admin.drain()
    assert await hub.flush() == 0  # nothing changed → nothing sent
    s = await container.repos.bus_states.get("B05")
    newer = s.model_copy(update={"ts": s.ts + timedelta(seconds=5)})
    await hub.on_bus_state(BusStateUpdated(ts=newer.ts, state=newer))
    await hub.on_bus_state(BusStateUpdated(ts=s.ts, state=s))  # late duplicate: ignored
    await _flush(container)
    msgs = await admin.drain()
    assert types(msgs).count("bus.state.updated") == 1
    assert of_type(msgs, "occupancy.updated") == []  # occupancy unchanged
    assert of_type(msgs, "eta.updated") == []  # same ETA → no event
    older = s.model_copy(update={"ts": s.ts - timedelta(seconds=30), "occupancy": 1})
    await hub.on_bus_state(BusStateUpdated(ts=older.ts, state=older))
    await _flush(container)
    assert of_type(await admin.drain(), "bus.state.updated") == []  # older than pushed → dropped
    fuller = newer.model_copy(
        update={"ts": newer.ts + timedelta(seconds=5), "occupancy": newer.occupancy + 3}
    )
    await hub.on_bus_state(BusStateUpdated(ts=fuller.ts, state=fuller))
    await _flush(container)
    occ = of_type(await admin.drain(), "occupancy.updated")
    assert occ[0]["data"]["passengers"] == newer.occupancy + 3  # BusState value as stored


async def test_flush_with_no_clients_does_no_work(live_client):
    _, container = live_client
    await advance(container, 60)
    hub = container.realtime()
    assert len(hub.manager) == 0
    assert await hub.flush() == 0


async def test_sim_reset_tells_everyone_to_resync(live_client, ws, student_headers):
    client, _ = live_client
    admin_h = await login(client, ADMIN)
    s, d = await ws(student_headers), await ws(await login(client, DRIVER07))
    assert (await client.post("/sim/reset", headers=admin_h)).status_code == 200
    for sock in (s, d):
        assert of_type(await sock.drain(), "sim.reset")


# ----------------------------------------------------------------------------- robustness


async def test_slow_or_failed_clients_never_break_publishing():
    from app.core.auth import Principal
    from app.models.common import Role

    mgr = ConnectionManager(queue_size=2)
    slow = mgr.connect(Principal(user_id="U-A1", role=Role.ADMIN), None)
    ok = mgr.connect(Principal(user_id="U-A2", role=Role.ADMIN), None)
    for _ in range(2):  # both queues fill up
        assert mgr.send("x", Audience.admins()) == 2
    ok.queue.get_nowait()  # the healthy client keeps reading…
    ok.queue.get_nowait()
    assert mgr.send("y", Audience.admins()) == 1  # slow queue full → dropped, not raised
    assert slow.closing == "too_slow" and slow.stop.is_set()
    assert mgr.send("z", Audience.admins()) == 1  # a closing connection gets nothing more

    from app.api.v1.ws import _writer

    class DeadSocket:
        async def send_text(self, _text: str) -> None:
            raise RuntimeError("socket gone")

    conn = mgr.connect(Principal(user_id="U-A3", role=Role.ADMIN), None)
    conn.offer("hello")
    await asyncio.wait_for(_writer(DeadSocket(), conn), 1)
    assert conn.closing == "send_failed" and conn.stop.is_set()


async def test_heartbeat_ping_and_idle_cleanup(live_client, student_headers):
    _, container = live_client
    container.settings = container.settings.model_copy(
        update={"ws_heartbeat_s": 0.05, "ws_idle_timeout_s": 0.3}
    )
    try:
        app = create_app(container=container)
        alive = await WsTestClient(app).connect()
        await alive.auth(student_headers)
        silent = await WsTestClient(app).connect()
        await silent.auth(student_headers)
        pings = 0
        for _ in range(12):  # ~0.6 s: answer every ping on one socket only
            try:
                m = await alive.recv(wait_s=0.2)
            except TimeoutError:
                continue
            if m["type"] == "ping":
                pings += 1
                await alive.send({"type": "pong"})
        assert pings >= 3
        assert await silent.wait_closed(wait_s=2) == 4410  # idle → closed and removed
        assert len(container.realtime().manager) == 1
        await alive.close()
        assert len(container.realtime().manager) == 0
    finally:
        await container.realtime().shutdown()


async def test_bus_status_values_come_from_tracking(live_client, ws):
    """The pushed status is BusState.status as tracking derived it (no realtime-side rules)."""
    client, container = live_client
    admin = await ws(await login(client, ADMIN))
    await advance(container, 5 * 60)
    await _flush(container)
    msgs = await admin.drain()
    for m in of_type(msgs, "bus.state.updated"):
        stored = await container.repos.bus_states.get(m["data"]["bus"]["id"])
        assert m["data"]["bus"]["live"]["status"] == stored.status.value
        assert stored.status in tuple(BusStatus)
