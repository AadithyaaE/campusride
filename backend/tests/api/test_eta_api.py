"""GET /buses/{id}/eta, GET /stops/{id}/arrivals, GET /students/me/arrivals."""

from __future__ import annotations

from tests.conftest import advance, login


async def test_bus_eta(live_client, student_headers):
    client, _ = live_client
    r = await client.get("/buses/B05/eta", params={"stop_id": "S27"}, headers=student_headers)
    assert r.status_code == 200
    e = r.json()
    assert (e["bus_id"], e["stop_id"], e["stop_name"], e["route_direction_id"]) == (
        "B05",
        "S27",
        "Sholinganallur Junction",
        "R3",
    )
    assert e["status"] == "predicted" and isinstance(e["eta_minutes"], int) and e["eta_minutes"] > 0
    assert isinstance(e["eta_seconds"], int)
    assert e["confidence"] in ("high", "medium", "low") and e["traffic"] in ("Low", "Moderate", "High")
    assert e["estimated_arrival_time"] and e["computed_at"]
    assert e["distance_to_stop_m"] > 0 and e["stops_away"] >= 1
    assert round(e["traffic_factor"], 2) == e["traffic_factor"]  # no excessive precision


async def test_bus_eta_errors_and_auth(live_client, student_headers):
    client, _ = live_client
    q = {"stop_id": "S27"}
    assert (await client.get("/buses/B05/eta", params=q)).status_code == 401
    assert (await client.get("/buses/B99/eta", params=q, headers=student_headers)).status_code == 404
    assert (
        await client.get("/buses/B05/eta", params={"stop_id": "S99"}, headers=student_headers)
    ).status_code == 404
    unrelated = await client.get("/buses/B01/eta", params={"stop_id": "S27"}, headers=student_headers)
    assert unrelated.status_code == 409 and "does not serve" in unrelated.json()["error"]["message"]
    assert (
        await client.get("/buses/B05/eta", headers=student_headers)
    ).status_code == 422  # stop_id required


async def test_passed_stop_eta(live_client, student_headers):
    client, container = live_client
    await advance(container, 12 * 60)
    r = await client.get("/buses/B05/eta", params={"stop_id": "S20"}, headers=student_headers)
    assert r.status_code == 200 and r.json()["status"] == "passed" and r.json()["eta_minutes"] is None


async def test_stop_arrivals_ordered_by_eta(live_client, student_headers):
    client, container = live_client
    await advance(container, 6 * 60)
    r = await client.get("/stops/S08/arrivals", params={"direction": "to_campus"}, headers=student_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["stop"]["id"] == "S08"
    arrivals = body["arrivals"]
    assert {a["route_direction_id"] for a in arrivals} == {"R1", "R2", "R5"}
    predicted = [a["eta"]["eta_seconds"] for a in arrivals if a["eta"]["status"] == "predicted"]
    assert predicted == sorted(predicted)
    a = arrivals[0]
    for key in (
        "bus_number",
        "route_name",
        "direction",
        "position",
        "match",
        "occupancy",
        "capacity",
        "delay_s",
        "last_updated",
    ):
        assert key in a
    assert set(a["eta"]) >= {"eta_minutes", "estimated_arrival_time", "traffic", "confidence"}
    assert (await client.get("/stops/S99/arrivals", headers=student_headers)).status_code == 404


async def test_student_arrivals(live_client, student_headers):
    client, _ = live_client
    a = (await client.get("/students/me/assignment", headers=student_headers)).json()["assignment"]
    body = (await client.get("/students/me/arrivals", headers=student_headers)).json()
    assert body["status"] == "assigned" and body["boarding_stop"]["id"] == a["boarding_stop"]["stop_id"]
    assert body["my_bus"]["bus_id"] == a["bus"]["id"] and body["my_bus"]["is_assigned_bus"] is True
    assert body["my_bus_serving_stop"] is True and body["my_bus"]["eta"]["status"] == "predicted"
    ids = [x["bus_id"] for x in body["arrivals"]]
    assert a["bus"]["id"] in ids
    secs = [x["eta"]["eta_seconds"] for x in body["arrivals"] if x["eta"]["status"] == "predicted"]
    assert secs == sorted(secs)
    assert all(x["direction"] == a["route"]["direction"] for x in body["arrivals"])


async def test_student_arrivals_unassigned_and_roles(live_client):
    client, _ = live_client
    new = await login(client, "student025@campusride.demo")
    body = (await client.get("/students/me/arrivals", headers=new)).json()
    assert body["status"] == "unassigned" and body["my_bus"] is None and body["arrivals"] == []
    admin = await login(client, "admin1@campusride.demo")
    assert (await client.get("/students/me/arrivals", headers=admin)).status_code == 403
    assert (await client.get("/students/me/arrivals")).status_code == 401
