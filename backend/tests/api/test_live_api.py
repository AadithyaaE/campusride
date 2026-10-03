"""Live bus state API, driver telemetry endpoint, simulator controls, lifespan."""

from __future__ import annotations

from app.deps import AppContainer
from app.main import attach_simulator, create_app
from app.models.common import BusStatus
from app.services.bus_simulator import _RUNNING
from tests.conftest import advance, login


async def test_buses_expose_synthetic_live_state(live_client, student_headers):
    client, container = live_client
    buses = (await client.get("/buses", headers=student_headers)).json()
    assert len(buses) == 12
    b = next(x for x in buses if x["id"] == "B05")
    assert b["source"] == "sim" and b["capacity"] == 50 and b["route_id"] == "R3"
    live = b["live"]
    assert live["status"] == "at_depot" and live["route_direction_id"] == "R3"
    assert live["location"]["type"] == "Point" and live["stale"] is False
    for key in (
        "speed_mps",
        "heading_deg",
        "current_stop_id",
        "next_stop_id",
        "route_progress",
        "occupancy",
        "last_updated",
        "schedule_status",
        "delay_s",
    ):
        assert key in live

    await advance(container, 10 * 60)
    moved = next(x for x in (await client.get("/buses", headers=student_headers)).json() if x["id"] == "B05")[
        "live"
    ]
    assert moved["route_progress"] > live["route_progress"]
    assert moved["location"] != live["location"]
    assert moved["last_updated"] > live["last_updated"]


async def test_bus_detail_and_assigned_bus_lookup(live_client, student_headers):
    client, container = live_client
    assignment = (await client.get("/students/me/assignment", headers=student_headers)).json()
    bus_id = assignment["assignment"]["bus"]["id"]
    await advance(container, 5 * 60)
    r = await client.get(f"/buses/{bus_id}", headers=student_headers)
    assert r.status_code == 200
    d = r.json()
    assert (
        d["id"] == bus_id
        and d["live"]["route_direction_id"] == assignment["assignment"]["route"]["route_direction_id"]
    )
    assert d["next_stop"]["id"] == d["live"]["next_stop_id"] and d["next_stop"]["name"]
    assert d["current_stop"]["id"] == d["live"]["current_stop_id"]
    assert d["simulation_paused"] is False
    assert (await client.get("/buses/B99", headers=student_headers)).status_code == 404
    # the simulator never touches assignments
    again = (await client.get("/students/me/assignment", headers=student_headers)).json()
    assert again == assignment


async def test_unassigned_students_stay_unassigned(live_client):
    client, container = live_client
    headers = await login(client, "student025@campusride.demo")
    await advance(container, 120)
    body = (await client.get("/students/me/assignment", headers=headers)).json()
    assert body["status"] == "unassigned" and body["assignment"] is None


async def test_driver_telemetry_endpoint_uses_the_same_ingest_path(live_client):
    client, container = live_client
    driver = await login(client, "driver05@campusride.demo")  # D05 drives B05
    trip_id = container.simulator.plan("B05").trips[0].trip.id
    s = container.simulator.plan("B05").trips[0].at(container.clock.now())
    body = {
        "bus_id": "B05",
        "trip_id": trip_id,
        "points": [
            {
                "ts": container.clock.now().isoformat(),
                "lng": s.lnglat[0],
                "lat": s.lnglat[1],
                "speed_mps": 0,
                "accuracy_m": 5,
            }
        ],
    }
    r = await client.post("/driver/telemetry", json=body, headers=driver)
    assert r.status_code == 202 and r.json()["status"] == "at_depot"
    stored = await container.repos.telemetry.recent("B05", since=container.clock.now())
    assert stored[-1].meta.source.value == "device"

    other_driver = await login(client, "driver01@campusride.demo")
    assert (await client.post("/driver/telemetry", json=body, headers=other_driver)).status_code == 403
    student = await login(client, "student001@campusride.demo")
    assert (await client.post("/driver/telemetry", json=body, headers=student)).status_code == 403
    wrong_trip = {**body, "trip_id": container.simulator.plan("B01").trips[0].trip.id}
    assert (await client.post("/driver/telemetry", json=wrong_trip, headers=driver)).status_code == 403


async def test_sim_controls(live_client, student_headers):
    client, container = live_client
    st = (await client.get("/sim/status", headers=student_headers)).json()
    assert st["enabled"] and st["controls_allowed"] and st["buses"] == 12
    assert st["allowed_speeds"] == [1, 2, 5, 10, 20]

    assert (await client.post("/sim/pause", headers=student_headers)).json()["paused"] is True
    detail = (await client.get("/buses/B05", headers=student_headers)).json()
    assert detail["simulation_paused"] is True
    assert (await client.post("/sim/start", headers=student_headers)).json()["paused"] is False
    assert (await client.put("/sim/speed", json={"speed": 20}, headers=student_headers)).json()["speed"] == 20
    assert (await client.put("/sim/speed", json={"speed": 7}, headers=student_headers)).status_code == 409

    await advance(container, 600)
    reset = (await client.post("/sim/reset", headers=student_headers)).json()
    assert reset["sim_time"] == reset["start_time"]
    b05 = (await client.get("/buses/B05", headers=student_headers)).json()
    assert b05["live"]["status"] == BusStatus.AT_DEPOT.value
    assert (await client.post("/sim/start")).status_code == 401


async def test_sim_controls_are_admin_only_outside_dev(live_client, student_headers):
    client, container = live_client
    container.settings = container.settings.model_copy(update={"app_env": "prod"})
    assert (await client.post("/sim/pause", headers=student_headers)).status_code == 403
    st = (await client.get("/sim/status", headers=student_headers)).json()
    assert st["controls_allowed"] is False
    admin = await login(client, "admin1@campusride.demo")
    assert (await client.post("/sim/pause", headers=admin)).status_code == 200


async def test_lifespan_starts_one_simulator_and_stops_it(container: AppContainer):
    attach_simulator(container)
    app = create_app(container=container)
    async with app.router.lifespan_context(app):
        sim = container.simulator
        assert sim is not None and sim.task_running
        assert sim.ensure_loop() is False  # already running — no duplicate
        assert len([s for s in _RUNNING if s.task_running]) == 1
        assert len(await container.repos.bus_states.list()) == 12
    assert not sim.task_running
    assert not [s for s in _RUNNING if s.task_running]
