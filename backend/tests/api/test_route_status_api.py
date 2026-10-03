"""GET /buses/{id}/route-status, POST /sim/route-deviation, GET /alerts (Feature 10)."""

from __future__ import annotations

from datetime import timedelta

from app.models.common import RouteStatus
from tests.conftest import advance, login


async def _status(client, headers, bus="B05"):
    r = await client.get(f"/buses/{bus}/route-status", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_requires_auth_and_known_bus(live_client, student_headers):
    client, _ = live_client
    assert (await client.get("/buses/B05/route-status")).status_code == 401
    assert (await client.get("/buses/B99/route-status", headers=student_headers)).status_code == 404


async def test_normal_schema_route_and_location(live_client, student_headers):
    client, container = live_client
    await advance(container, 5 * 60)
    body = await _status(client, student_headers)
    assert body["route_status"] == "NORMAL" and body["source"] == "synthetic"
    assert 0 <= body["deviation_distance_m"] <= 50
    assert body["thresholds"] == {"minor_m": 50.0, "major_m": 150.0}
    assert (body["trip_id"], body["route_id"], body["route_direction_id"]) == (
        (await container.repos.bus_states.get("B05")).trip_id,
        "R3",
        "R3",
    )
    # expected route = the authored R3 geometry in the direction of travel (not the stops)
    route = await container.repos.routes.get("R3")
    assert body["expected_route"]["type"] == "LineString"
    assert len(body["expected_route"]["coordinates"]) == len(route.path.coordinates)
    state = await container.repos.bus_states.get("B05")
    assert body["current_location"] == {
        "lat": state.location.coordinates[1],
        "lon": state.location.coordinates[0],
    }  # the TRACKED point — the one the maps show
    assert body["timestamp"] and body["evaluated_at"] and body["message"] is None
    assert body["major_alert_active"] is False


async def test_minor_and_major_via_simulator_controls(live_client, student_headers):
    client, container = live_client
    await advance(container, 5 * 60)
    admin = await login(client, "admin1@campusride.demo")
    r = await client.post("/sim/route-deviation", json={"mode": "minor", "bus_id": "B05"}, headers=admin)
    assert r.status_code == 200 and r.json()["route_deviation"] == {"B05": "minor"}
    await advance(container, 30)
    minor = await _status(client, student_headers)
    assert minor["route_status"] == "MINOR_DEVIATION" and 50 < minor["deviation_distance_m"] < 150
    assert minor["message"].startswith("BUS B05 is ") and minor["major_alert_active"] is False

    await client.post("/sim/route-deviation", json={"mode": "major", "bus_id": "B05"}, headers=admin)
    await advance(container, 30)
    major = await _status(client, student_headers)
    assert major["route_status"] == "MAJOR_DEVIATION" and major["deviation_distance_m"] >= 150
    assert major["major_alert_active"] is True and major["nearest_route_point"] is not None
    # the same status flows into the existing live payloads
    fleet = {b["id"]: b for b in (await client.get("/buses", headers=student_headers)).json()}
    assert fleet["B05"]["live"]["route_status"] == "MAJOR_DEVIATION"
    assert fleet["B05"]["live"]["status"] == "deviated"
    arrivals = (await client.get("/students/me/arrivals", headers=student_headers)).json()
    assert arrivals["my_bus"]["route_status"] == "MAJOR_DEVIATION"

    alerts = (await client.get("/alerts", params={"active": True}, headers=admin)).json()
    assert len(alerts) == 1 and alerts[0]["type"] == "deviation" and alerts[0]["active"] is True
    assert alerts[0]["payload"]["bus_id"] == "B05" and alerts[0]["severity"] == "critical"
    for _ in range(5):  # polling never creates alerts
        await _status(client, student_headers)
    assert len((await client.get("/alerts", headers=admin)).json()) == 1

    await client.post("/sim/route-deviation", json={"mode": "normal", "bus_id": "B05"}, headers=admin)
    await advance(container, 30)
    assert (await _status(client, student_headers))["route_status"] == "NORMAL"
    assert (await client.get("/alerts", params={"active": True}, headers=admin)).json() == []
    resolved = (await client.get("/alerts", headers=admin)).json()
    assert resolved[0]["active"] is False and resolved[0]["resolved_at"]


async def test_no_active_trip_and_stale(live_client, student_headers):
    client, container = live_client
    await advance(container, 60)
    state = await container.repos.bus_states.get("B05")
    await container.repos.bus_states.upsert(state.model_copy(update={"trip_id": None}))
    body = await _status(client, student_headers)
    assert body["route_status"] == RouteStatus.NO_ACTIVE_TRIP
    assert body["expected_route"] is None and body["deviation_distance_m"] is None  # no invented route
    await container.repos.bus_states.upsert(
        state.model_copy(update={"last_seen": state.last_seen - timedelta(minutes=5)})
    )
    stale = await _status(client, student_headers)
    assert stale["route_status"] == "STALE" and stale["deviation_distance_m"] is None


async def test_simulator_control_permissions_and_validation(live_client, student_headers, container):
    client, _ = live_client
    # dev/test: any signed-in user may use demo controls (existing convention); prod: admins only
    r = await client.post("/sim/route-deviation", json={"mode": "major"}, headers=student_headers)
    assert r.status_code == 200 and r.json()["route_deviation"] == {"*": "major"}
    assert (await client.post("/sim/route-deviation", json={"mode": "major"})).status_code == 401
    bad = await client.post("/sim/route-deviation", json={"mode": "sideways"}, headers=student_headers)
    assert bad.status_code == 422
    unknown = await client.post(
        "/sim/route-deviation", json={"mode": "major", "bus_id": "B99"}, headers=student_headers
    )
    assert unknown.status_code == 404
    reset = await client.post("/sim/reset", headers=student_headers)
    assert reset.json()["route_deviation"] == {}  # reset → NORMAL
    container.settings = container.settings.model_copy(update={"app_env": "prod"})
    r = await client.post("/sim/route-deviation", json={"mode": "major"}, headers=student_headers)
    assert r.status_code == 403


async def test_alerts_are_admin_only(live_client, student_headers):
    client, _ = live_client
    assert (await client.get("/alerts", headers=student_headers)).status_code == 403
    assert (await client.get("/alerts")).status_code == 401
