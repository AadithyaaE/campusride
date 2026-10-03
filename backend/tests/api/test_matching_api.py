"""GET /stops/{id}/buses and GET /students/me/stop/buses (live simulator state)."""

from __future__ import annotations

from tests.conftest import advance, login


async def test_stop_buses_lists_buses_whose_direction_serves_the_stop(live_client, student_headers):
    client, _ = live_client
    r = await client.get("/stops/S08/buses", headers=student_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["stop"] == {"id": "S08", "name": "Medavakkam Koot Road"}
    assert {b["route_direction_id"] for b in body["buses"]} == {"R1", "R2", "R5"}
    b = body["buses"][0]
    for key in (
        "bus_id",
        "bus_number",
        "reg_no",
        "capacity",
        "route_id",
        "route_name",
        "direction",
        "direction_label",
        "status",
        "occupancy",
        "last_updated",
        "route_progress",
        "position",
        "match",
    ):
        assert key in b
    assert (
        b["position"]["current_stop"]["name"]
        and "next_stop" in b["position"]
        and "previous_stop" in b["position"]
    )
    assert b["match"]["stop_id"] == "S08" and b["match"]["position"] == "ahead"
    assert "qr_secret" not in r.text

    evening = await client.get(
        "/stops/S08/buses", params={"direction": "from_campus"}, headers=student_headers
    )
    assert evening.json()["buses"] == []
    assert (await client.get("/stops/S99/buses", headers=student_headers)).status_code == 404
    assert (await client.get("/stops/S08/buses")).status_code == 401


async def test_stop_buses_track_progress_toward_the_stop(live_client, student_headers):
    client, container = live_client
    before = {
        b["bus_id"]: b
        for b in (await client.get("/stops/S27/buses", headers=student_headers)).json()["buses"]
    }
    await advance(container, 8 * 60)
    after = {
        b["bus_id"]: b
        for b in (await client.get("/stops/S27/buses", headers=student_headers)).json()["buses"]
    }
    b05_before, b05_after = before["B05"]["match"], after["B05"]["match"]
    assert b05_after["distance_to_stop_m"] < b05_before["distance_to_stop_m"]
    assert b05_after["progress_to_stop"] > b05_before["progress_to_stop"]
    assert after["B05"]["position"]["current_stop"]["seq"] >= before["B05"]["position"]["current_stop"]["seq"]


async def test_my_stop_buses_for_an_assigned_student(live_client, student_headers):
    client, _ = live_client
    a = (await client.get("/students/me/assignment", headers=student_headers)).json()["assignment"]
    r = await client.get("/students/me/stop/buses", headers=student_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "assigned"
    assert body["boarding_stop"]["id"] == a["boarding_stop"]["stop_id"]
    assert (
        body["assigned_bus_id"] == a["bus"]["id"]
        and body["route_direction_id"] == a["route"]["route_direction_id"]
    )
    assert body["my_bus"]["bus_id"] == a["bus"]["id"] and body["my_bus"]["is_assigned_bus"] is True
    assert (
        body["my_bus_serving_stop"] is True
        and body["my_bus"]["match"]["stop_id"] == a["boarding_stop"]["stop_id"]
    )
    others = body["other_buses"]
    assert others and all(not o["is_assigned_bus"] for o in others)
    assert all(o["direction"] == a["route"]["direction"] for o in others)
    assert a["bus"]["id"] not in {o["bus_id"] for o in others}
    # read-only: the assignment is unchanged
    assert (await client.get("/students/me/assignment", headers=student_headers)).json()["assignment"] == a


async def test_my_stop_buses_unassigned_and_roles(live_client):
    client, _ = live_client
    new_student = await login(client, "student025@campusride.demo")
    body = (await client.get("/students/me/stop/buses", headers=new_student)).json()
    assert body == {
        "student_id": "U-S0025",
        "status": "unassigned",
        "boarding_stop": None,
        "assigned_bus_id": None,
        "route_direction_id": None,
        "direction": None,
        "my_bus": None,
        "my_bus_serving_stop": False,
        "other_buses": [],
    }
    admin = await login(client, "admin1@campusride.demo")
    assert (await client.get("/students/me/stop/buses", headers=admin)).status_code == 403
