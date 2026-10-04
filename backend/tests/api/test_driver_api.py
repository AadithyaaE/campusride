"""Feature 12 — Driver App backend: /driver/me, trip start/stop, simulated GPS, route view.

B07 (driver D07 "Arun Kumar") is driver-controlled here; every other bus keeps the
automatic demo schedule. All three apps read the SAME BusState.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.models import User
from app.models.common import Role, TripStatus
from tests.conftest import SEED, advance, login

DRIVER = "driver07@campusride.demo"


@pytest.fixture
def settings() -> Settings:  # overrides the session fixture for this module only
    return Settings(
        _env_file=None,
        app_env="test",
        seed=SEED,
        mock_token_secret="test-secret",
        sim_driver_controlled_buses="B07",
    )


async def _me(client, headers):
    r = await client.get("/driver/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_driver_sees_own_assignment_ready(live_client):
    client, _ = live_client
    d = await login(client, DRIVER)
    me = await _me(client, d)
    assert me["driver"]["name"] == "Arun Kumar" and me["driver"]["id"] == "D07"
    assert (me["bus"]["id"], me["bus"]["capacity"]) == ("B07", 50)
    assert me["route"]["id"] == "R4" and me["route"]["route_direction_id"] == "R4"
    assert me["trip_state"] == "READY" and me["control"] == "driver"
    assert me["can_start"] is True and me["can_stop"] is False
    assert me["trip"]["status"] == "scheduled" and me["next_stop"] == me["trip"]["first_stop"]
    # waiting at the first stop: the simulator already reports it (synthetic GPS)
    assert me["gps"] == "LIVE" and me["gps_source"] == "simulated"
    assert me["live"]["bus_status"] == "at_depot" and me["live"]["speed_kmh"] == 0


async def test_role_and_auth_rules(live_client, student_headers):
    client, _ = live_client
    assert (await client.get("/driver/me")).status_code == 401
    assert (await client.get("/driver/me", headers=student_headers)).status_code == 403
    admin = await login(client, "admin1@campusride.demo")
    assert (await client.post("/driver/trip/start", headers=admin)).status_code == 403
    d = await login(client, DRIVER)
    # drivers can't use student-only or admin-only APIs
    assert (await client.get("/students/me/assignment", headers=d)).status_code == 403
    assert (await client.get("/alerts", headers=d)).status_code == 403
    assert (await client.get("/students/U-S0001/bus-options", headers=d)).status_code == 403


async def test_full_trip_end_to_end(live_client, student_headers):
    """THE Feature 12 integration test: driver → simulator → telemetry → tracking → all apps."""
    client, container = live_client
    d = await login(client, DRIVER)
    admin = await login(client, "admin1@campusride.demo")

    # 1–2. start → ACTIVE (backend state)
    r = await client.post("/driver/trip/start", headers=d)
    assert r.status_code == 200, r.text
    started = r.json()
    assert started["trip_state"] == "ACTIVE" and started["trip"]["status"] == "active"
    assert started["trip"]["actual_start"] and started["can_stop"] is True
    trip_id = started["trip"]["id"]
    assert (await container.repos.trips.get(trip_id)).status is TripStatus.ACTIVE
    dup = await client.post("/driver/trip/start", headers=d)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "trip_already_active"

    # 3–4. the existing simulator produces telemetry; BusState updates
    first_fix = (await container.repos.bus_states.get("B07")).ts
    await advance(container, 6 * 60)
    state = await container.repos.bus_states.get("B07")
    assert state.ts > first_fix and state.trip_id == trip_id
    assert state.distance_along_m > 0 and state.status.value in ("en_route", "dwelling")

    # 7. the driver sees the backend's speed / location / next stop / occupancy
    me = await _me(client, d)
    assert me["gps"] == "LIVE" and me["trip_state"] == "ACTIVE"
    assert me["live"]["location"] == {
        "lat": state.location.coordinates[1],
        "lon": state.location.coordinates[0],
    }
    assert me["live"]["speed_kmh"] == round(state.speed_mps * 3.6)
    assert me["live"]["occupancy"] == state.occupancy and me["live"]["capacity"] == 50
    assert me["next_stop"] == me["live"]["next_stop"] and me["next_stop"]

    # 5–6. student and admin endpoints show the SAME bus state
    for headers in (student_headers, admin):
        fleet = {b["id"]: b for b in (await client.get("/buses", headers=headers)).json()}
        live = fleet["B07"]["live"]
        assert live["trip_id"] == trip_id and live["status"] == state.status.value
        assert live["location"]["coordinates"] == list(state.location.coordinates)
        assert live["occupancy"] == me["live"]["occupancy"]
    occ = (await client.get("/buses/B07/occupancy", headers=d)).json()
    assert (
        occ["occupancy"] == me["live"]["occupancy"]
        and occ["available_seats"] == me["live"]["available_seats"]
    )
    rs = (await client.get("/buses/B07/route-status", headers=admin)).json()
    assert rs["route_status"] == "NORMAL" and rs["trip_id"] == trip_id

    # route view: ordered stops with progress from tracking
    view = (await client.get("/driver/route", headers=d)).json()
    assert view["trip_id"] == trip_id and view["route"]["id"] == "R4"
    states = [s["state"] for s in view["stops"]]
    assert states[0] in ("passed", "current") and "next" in states and states[-1] == "upcoming"
    assert view["path"]["type"] == "LineString" and view["bus_location"]

    # 8–9. stop → finalized where the bus is
    r = await client.post("/driver/trip/stop", headers=d)
    assert r.status_code == 200, r.text
    stopped = r.json()
    assert stopped["trip_state"] in ("READY", "COMPLETED") and stopped["trip"]["id"] != trip_id
    trip = await container.repos.trips.get(trip_id)
    assert trip.status is TripStatus.COMPLETED and trip.actual_end is not None
    final = await container.repos.bus_states.get("B07")
    assert final.status.value == "completed" and final.trip_id == trip_id
    fleet = {b["id"]: b for b in (await client.get("/buses", headers=student_headers)).json()}
    assert fleet["B07"]["live"]["status"] == "completed"  # students see completion

    # 10. telemetry stops for that trip (the phone goes quiet until the next trip's window)
    await advance(container, 3 * 60)
    assert (await container.repos.bus_states.get("B07")).ts == final.ts
    again = await client.post("/driver/trip/stop", headers=d)
    assert again.status_code == 409 and again.json()["error"]["code"] == "no_active_trip"


async def test_other_buses_keep_the_automatic_schedule(live_client):
    client, container = live_client
    await advance(container, 5 * 60)
    b05 = await container.repos.bus_states.get("B05")
    b07 = await container.repos.bus_states.get("B07")
    assert b05.status.value in ("en_route", "dwelling")  # departed by itself
    assert b07.status.value == "at_depot"  # waits for its driver
    d05 = await login(client, "driver05@campusride.demo")
    me = await _me(client, d05)
    assert me["control"] == "schedule" and me["can_start"] is False and me["message"]
    r = await client.post("/driver/trip/start", headers=d05)
    assert r.status_code == 409 and r.json()["error"]["code"] == "schedule_controlled"


async def test_wrong_driver_cannot_control_or_send_telemetry_for_another_bus(live_client):
    client, container = live_client
    d07 = await login(client, DRIVER)
    await client.post("/driver/trip/start", headers=d07)
    d05 = await login(client, "driver05@campusride.demo")
    r = await client.post("/driver/trip/stop", headers=d05)  # acts on B05 only → nothing to stop
    assert r.status_code == 409
    assert (
        await container.repos.trips.get((await _me(client, d07))["trip"]["id"])
    ).status is TripStatus.ACTIVE
    tele = {
        "bus_id": "B07",
        "trip_id": None,
        "points": [{"ts": "2026-10-05T01:50:00Z", "lng": 80.2, "lat": 12.9, "speed_mps": 5}],
    }
    assert (await client.post("/driver/telemetry", json=tele, headers=d05)).status_code == 403


async def test_simulate_gps_pushes_one_fix_through_the_pipeline(live_client):
    client, container = live_client
    d = await login(client, DRIVER)
    await client.post("/driver/trip/start", headers=d)
    container.clock.advance(2)  # off the 5 s telemetry grid
    before = (await container.repos.bus_states.get("B07")).ts
    r = await client.post("/driver/simulate-gps", headers=d)
    assert r.status_code == 200 and r.json()["gps"] == "LIVE"
    after = await container.repos.bus_states.get("B07")
    assert after.ts > before and after.ts == container.clock.now()
    await client.post("/driver/trip/stop", headers=d)
    await advance(container, 60)
    quiet = await client.post("/driver/simulate-gps", headers=d)  # evening trip is hours away
    assert quiet.status_code == 409 and quiet.json()["error"]["code"] == "gps_unavailable"


async def test_qr_boarding_shows_in_the_driver_passenger_count(live_client):
    client, container = live_client
    d = await login(client, DRIVER)
    await client.post("/driver/trip/start", headers=d)
    await advance(container, 60)
    assigned = sorted(a.id for a in await container.repos.student_assignments.for_bus("B07"))
    before = (await _me(client, d))["live"]["occupancy"]
    for sid in assigned:  # first assigned student whose stop is still ahead
        user = await container.repos.users.get(sid)
        headers = await login(client, user.email)
        me = (await client.get("/students/me/boarding", headers=headers)).json()
        if not me["ready"]:
            continue
        payload = {k: me[k] for k in ("student_id", "bus_id", "trip_id")} | {
            "timestamp": "2026-10-05T01:47:00Z"
        }
        r = await client.post("/boarding/scan", json=payload, headers=headers)
        assert r.status_code == 200, r.text
        break
    else:
        pytest.fail("no boardable B07 student")
    after = (await _me(client, d))["live"]
    assert after["occupancy"] == min(50, before + 1)  # the Feature 8 occupancy, unchanged logic


async def test_trip_completes_by_itself_at_the_terminal(live_client):
    client, container = live_client
    d = await login(client, DRIVER)
    started = (await client.post("/driver/trip/start", headers=d)).json()
    trip_id = started["trip"]["id"]
    await advance(container, 90 * 60)
    assert (await container.repos.trips.get(trip_id)).status is TripStatus.COMPLETED
    assert (await container.repos.bus_states.get("B07")).status.value == "completed"


async def test_no_assignment_and_invalid_driver(live_client):
    client, container = live_client
    bus = await container.repos.buses.get("B07")
    await container.repos.buses.upsert(bus.model_copy(update={"driver_id": None}))
    d = await login(client, DRIVER)
    me = await _me(client, d)
    assert me["trip_state"] == "NO_ASSIGNMENT" and me["bus"] is None and me["message"]
    r = await client.post("/driver/trip/start", headers=d)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_assignment"
    await container.repos.users.upsert(
        User(id="U-D99", role=Role.DRIVER, name="Ghost Driver", email="ghost@campusride.demo")
    )
    ghost = await login(client, "ghost@campusride.demo")
    r = await client.get("/driver/me", headers=ghost)
    assert r.status_code == 404 and r.json()["error"]["code"] == "invalid_driver"


async def test_simulator_unavailable(client):
    d = await login(client, DRIVER)
    r = await client.post("/driver/trip/start", headers=d)
    assert r.status_code == 503
    me = (await client.get("/driver/me", headers=d)).json()
    assert me["control"] == "schedule" and me["gps"] == "UNAVAILABLE"


async def test_reset_returns_the_driver_bus_to_ready(live_client):
    client, container = live_client
    d = await login(client, DRIVER)
    await client.post("/driver/trip/start", headers=d)
    await container.simulator.reset()
    me = await _me(client, d)
    assert me["trip_state"] == "READY" and me["can_start"] is True
