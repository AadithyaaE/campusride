"""GET /students/me/recovery-options and GET /students/{id}/recovery-options (Feature 9)."""

from __future__ import annotations

from tests.conftest import advance, login

OPTION_FIELDS = {
    "bus_id",
    "bus_number",
    "trip_id",
    "route_direction_id",
    "boarding_stop_id",
    "boarding_stop_name",
    "eta_minutes",
    "estimated_arrival_time",
    "occupancy",
    "capacity",
    "available_seats",
    "occupancy_percentage",
    "status",
    "delay_minutes",
    "distance_to_stop_m",
    "catchable",
    "safety_buffer_minutes",
    "reason",
}


async def test_not_needed_while_assigned_bus_is_catchable(live_client, student_headers):
    client, _ = live_client
    body = (await client.get("/students/me/recovery-options", headers=student_headers)).json()
    assert body["status"] == "not_needed" and body["trigger"] is None
    assert body["commute_decision"] == "YES"
    assert body["recommended"] is None and body["alternatives"] == []
    assert (body["assigned_bus_id"], body["assigned_bus"], body["boarding_stop_id"]) == (
        "B05",
        "BUS B05",
        "S27",
    )


async def test_recovery_when_at_risk(live_client, student_headers):
    client, container = live_client
    await advance(container, 20 * 60)
    r = await client.get("/students/me/recovery-options", headers=student_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "recovery_available" and body["trigger"] == "likely_to_miss"
    assert body["commute_decision"] == "RISK"  # Feature 7's decision is reported unchanged
    rec = body["recommended"]
    assert OPTION_FIELDS <= set(rec)
    assert rec["bus_id"] != "B05" and rec["boarding_stop_id"] == "S27"
    assert rec["catchable"] is True and rec["safety_buffer_minutes"] >= body["required_buffer_minutes"]
    assert rec["available_seats"] == rec["capacity"] - rec["occupancy"]
    assert rec["status"] in ("on_time", "delayed") and isinstance(rec["eta_minutes"], int)
    assert rec["bus_id"] in rec["reason"] and str(rec["safety_buffer_minutes"]) in rec["reason"]
    assert len(body["alternatives"]) <= 3
    assert all(o["boarding_stop_id"] == "S27" for o in body["alternatives"])
    assert "score" not in rec and "cost" not in rec


async def test_recovery_when_missed(live_client, student_headers):
    client, container = live_client
    await advance(container, 36 * 60)
    body = (await client.get("/students/me/recovery-options", headers=student_headers)).json()
    assert body["commute_decision"] == "MISSED" and body["trigger"] == "missed"
    assert body["status"] in ("recovery_available", "no_alternative")
    assert body["assigned_bus_id"] == "B05"  # never reassigned


async def test_query_parameters_cannot_override_assignment(live_client, student_headers):
    client, container = live_client
    await advance(container, 20 * 60)
    plain = (await client.get("/students/me/recovery-options", headers=student_headers)).json()
    tricked = (
        await client.get(
            "/students/me/recovery-options",
            params={"student_id": "U-S0002", "stop_id": "S08", "bus_id": "B11"},
            headers=student_headers,
        )
    ).json()
    keys = ("student_id", "assigned_bus_id", "boarding_stop_id")
    assert {k: tricked[k] for k in keys} == {k: plain[k] for k in keys}


async def test_unassigned_student(live_client):
    client, _ = live_client
    new = await login(client, "student025@campusride.demo")
    body = (await client.get("/students/me/recovery-options", headers=new)).json()
    assert body["status"] == "unassigned" and body["recommended"] is None and body["alternatives"] == []


async def test_authorization(live_client, student_headers):
    client, _ = live_client
    path = "/students/{}/recovery-options"
    assert (await client.get("/students/me/recovery-options")).status_code == 401
    assert (await client.get(path.format("U-S0001"))).status_code == 401
    own = await client.get(path.format("U-S0001"), headers=student_headers)
    assert own.status_code == 200 and own.json()["student_id"] == "U-S0001"
    assert (await client.get(path.format("U-S0002"), headers=student_headers)).status_code == 403
    assert (await client.get(path.format("U-NOPE"), headers=student_headers)).status_code == 403
    admin = await login(client, "admin1@campusride.demo")
    assert (await client.get("/students/me/recovery-options", headers=admin)).status_code == 403
    other = await client.get(path.format("U-S0002"), headers=admin)
    assert other.status_code == 200 and other.json()["student_id"] == "U-S0002"
    assert (await client.get(path.format("U-NOPE"), headers=admin)).status_code == 404
    driver = await login(client, "driver05@campusride.demo")
    assert (await client.get(path.format("U-S0001"), headers=driver)).status_code == 403
