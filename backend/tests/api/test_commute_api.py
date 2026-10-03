"""GET /students/me/commute-decision and GET /students/{id}/commute-decision (Feature 7)."""

from __future__ import annotations

from tests.conftest import advance, login

FIELDS = {
    "student_id",
    "status",
    "decision",
    "reason",
    "bus_id",
    "bus_number",
    "boarding_stop",
    "student_location",
    "walking_distance_m",
    "walking_speed_mps",
    "walking_time_minutes",
    "bus_eta_minutes",
    "bus_arrival_time",
    "required_arrival_time",
    "safety_buffer_minutes",
    "spare_minutes",
    "delay_minutes",
    "stale",
    "eta",
    "alternatives_available",
    "computed_at",
}


async def test_assigned_student_decision(live_client, student_headers):
    client, _ = live_client
    a = (await client.get("/students/me/assignment", headers=student_headers)).json()["assignment"]
    r = await client.get("/students/me/commute-decision", headers=student_headers)
    assert r.status_code == 200
    body = r.json()
    assert FIELDS <= set(body)
    assert body["status"] == "assigned" and body["decision"] == "YES"
    assert body["reason"] == "You should reach your stop before the bus."
    assert body["bus_id"] == a["bus"]["id"]  # derived from the assignment only
    assert body["boarding_stop"]["id"] == a["boarding_stop"]["stop_id"]
    assert body["student_location"]["source"] == "synthetic"
    assert isinstance(body["walking_distance_m"], int) and body["walking_distance_m"] > 0
    assert isinstance(body["walking_time_minutes"], int) and isinstance(body["bus_eta_minutes"], int)
    assert body["safety_buffer_minutes"] == 2
    assert body["bus_arrival_time"] == body["eta"]["estimated_arrival_time"]  # Feature 5 timestamp
    assert body["required_arrival_time"] < body["bus_arrival_time"]
    assert "probability" not in body and "score" not in body


async def test_query_parameters_cannot_substitute_bus_or_stop(live_client, student_headers):
    client, _ = live_client
    plain = (await client.get("/students/me/commute-decision", headers=student_headers)).json()
    tricked = (
        await client.get(
            "/students/me/commute-decision",
            params={"bus_id": "B11", "stop_id": "S08"},
            headers=student_headers,
        )
    ).json()
    assert (tricked["bus_id"], tricked["boarding_stop"]["id"]) == (
        plain["bus_id"],
        plain["boarding_stop"]["id"],
    )


async def test_missed_after_bus_passes(live_client, student_headers):
    client, container = live_client
    await advance(container, 36 * 60)
    body = (await client.get("/students/me/commute-decision", headers=student_headers)).json()
    assert body["decision"] == "MISSED" and "B05" == body["bus_id"]
    assert body["alternatives_available"] >= 1


async def test_unassigned_student(live_client):
    client, _ = live_client
    new = await login(client, "student025@campusride.demo")
    body = (await client.get("/students/me/commute-decision", headers=new)).json()
    assert body["status"] == "unassigned" and body["decision"] is None and body["bus_id"] is None


async def test_authorization(live_client, student_headers):
    client, _ = live_client
    path = "/students/{}/commute-decision"
    assert (await client.get("/students/me/commute-decision")).status_code == 401
    admin = await login(client, "admin1@campusride.demo")
    assert (await client.get("/students/me/commute-decision", headers=admin)).status_code == 403
    driver = await login(client, "driver05@campusride.demo")
    assert (await client.get("/students/me/commute-decision", headers=driver)).status_code == 403

    own = await client.get(path.format("U-S0001"), headers=student_headers)
    assert own.status_code == 200 and own.json()["student_id"] == "U-S0001"
    assert (await client.get(path.format("U-S0002"), headers=student_headers)).status_code == 403
    assert (await client.get(path.format("U-NOPE"), headers=student_headers)).status_code == 403
    assert (await client.get(path.format("U-S0001"), headers=driver)).status_code == 403
    assert (await client.get(path.format("U-S0001"))).status_code == 401

    other = await client.get(path.format("U-S0002"), headers=admin)
    assert other.status_code == 200 and other.json()["student_id"] == "U-S0002"
    assert (await client.get(path.format("U-NOPE"), headers=admin)).status_code == 404
    unassigned = await client.get(path.format("U-S0025"), headers=admin)
    assert unassigned.status_code == 200 and unassigned.json()["status"] == "unassigned"
