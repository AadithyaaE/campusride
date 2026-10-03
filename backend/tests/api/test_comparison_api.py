"""GET /students/me/bus-options and GET /students/{id}/bus-options (Feature 6)."""

from __future__ import annotations

from tests.conftest import advance, login

INDICATORS = {"ASSIGNED", "FASTEST", "LEAST_CROWDED", "BEST_ALTERNATIVE"}


async def test_my_bus_options(live_client, student_headers):
    client, container = live_client
    await advance(container, 24 * 60)
    a = (await client.get("/students/me/assignment", headers=student_headers)).json()["assignment"]
    r = await client.get("/students/me/bus-options", headers=student_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "assigned" and body["student_id"] == "U-S0001"
    assert body["boarding_stop"]["id"] == a["boarding_stop"]["stop_id"]  # correct boarding stop
    assert body["assigned_bus_id"] == a["bus"]["id"] and body["assigned_bus_available"] is True
    assert body["assigned_bus_note"] is None and body["computed_at"]
    options = body["options"]
    assert len(options) >= 3  # multiple buses serve Sholinganallur Junction
    assert all(o["direction"] == a["route"]["direction"] for o in options)  # correct direction
    assert all(o["match"]["stop_id"] == a["boarding_stop"]["stop_id"] for o in options)
    secs = [o["eta"]["eta_seconds"] for o in options]
    assert secs == sorted(secs)  # arrival order, not cost order

    mine = [o for o in options if o["is_assigned_bus"]]
    assert len(mine) == 1 and mine[0]["bus_id"] == a["bus"]["id"] and "ASSIGNED" in mine[0]["indicators"]
    assert sum("FASTEST" in o["indicators"] for o in options) == 1
    assert sum("LEAST_CROWDED" in o["indicators"] for o in options) == 1

    o = options[0]
    for key in (
        "bus_id",
        "bus_number",
        "reg_no",
        "occupancy",
        "capacity",
        "occupancy_percentage",
        "seats_available",
        "crowding",
        "delay_minutes",
        "status",
        "stale",
        "comparable",
        "indicators",
        "trade_off",
        "match",
        "eta",
    ):
        assert key in o, key
    assert isinstance(o["occupancy_percentage"], int) and o["crowding"] in ("Low", "Medium", "High")
    assert isinstance(o["delay_minutes"], int) and isinstance(o["eta"]["eta_minutes"], int)
    assert o["eta"]["traffic"] in ("Low", "Moderate", "High")
    assert o["eta"]["confidence"] in ("high", "medium", "low")
    assert set(o["indicators"]) <= INDICATORS
    assert "cost" not in o and "score" not in o  # the comparison cost stays internal
    assert body["excluded"] == [] or {"bus_id", "reason"} <= set(body["excluded"][0])


async def test_passed_assigned_bus_is_explained_not_offered(live_client, student_headers):
    client, container = live_client
    await advance(container, 42 * 60)
    body = (await client.get("/students/me/bus-options", headers=student_headers)).json()
    assert body["assigned_bus_available"] is False and "B05" in body["assigned_bus_note"]
    assert "B05" not in {o["bus_id"] for o in body["options"]}
    assert "B05" in {x["bus_id"] for x in body["excluded"]}
    assert all(o["eta"]["status"] in ("predicted", "at_stop") for o in body["options"])


async def test_unassigned_student(live_client):
    client, _ = live_client
    new = await login(client, "student025@campusride.demo")
    body = (await client.get("/students/me/bus-options", headers=new)).json()
    assert body["status"] == "unassigned" and body["options"] == [] and body["boarding_stop"] is None


async def test_authorization(live_client, student_headers):
    client, _ = live_client
    assert (await client.get("/students/me/bus-options")).status_code == 401
    admin = await login(client, "admin1@campusride.demo")
    assert (await client.get("/students/me/bus-options", headers=admin)).status_code == 403  # not a student
    driver = await login(client, "driver05@campusride.demo")
    assert (await client.get("/students/me/bus-options", headers=driver)).status_code == 403

    # by id: the student themself, or an admin — never another student
    own = await client.get("/students/U-S0001/bus-options", headers=student_headers)
    assert own.status_code == 200 and own.json()["student_id"] == "U-S0001"
    other = await client.get("/students/U-S0002/bus-options", headers=student_headers)
    assert other.status_code == 403
    probe = await client.get("/students/U-NOPE/bus-options", headers=student_headers)
    assert probe.status_code == 403  # no probing of which ids exist
    assert (await client.get("/students/U-S0001/bus-options", headers=driver)).status_code == 403
    assert (await client.get("/students/U-S0001/bus-options")).status_code == 401

    as_admin = await client.get("/students/U-S0002/bus-options", headers=admin)
    assert as_admin.status_code == 200 and as_admin.json()["student_id"] == "U-S0002"
    assert (await client.get("/students/U-NOPE/bus-options", headers=admin)).status_code == 404
    assert (await client.get("/students/D01/bus-options", headers=admin)).status_code == 404
