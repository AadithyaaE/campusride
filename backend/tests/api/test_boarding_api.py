"""POST /boarding/scan, GET /buses/{id}/occupancy, GET /trips/{id}/boarding, GET /students/me/boarding."""

from __future__ import annotations

from app.models.common import TripStatus
from tests.conftest import advance, login


async def _payload(client, headers):
    me = (await client.get("/students/me/boarding", headers=headers)).json()
    assert me["status"] == "assigned" and me["ready"] is True, me
    return {
        "student_id": me["student_id"],
        "bus_id": me["bus_id"],
        "trip_id": me["trip_id"],
        "timestamp": "2026-10-05T01:48:00Z",
        "stop_id": me["boarding_stop"]["id"],
    }


async def test_scan_requires_authentication(live_client):
    client, _ = live_client
    body = {"student_id": "U-S0001", "bus_id": "B05", "trip_id": "T", "timestamp": "2026-10-05T01:48:00Z"}
    assert (await client.post("/boarding/scan", json=body)).status_code == 401


async def test_valid_then_duplicate_scan(live_client, student_headers):
    client, container = live_client
    await advance(container, 3 * 60)
    before = (await client.get("/buses/B05/occupancy", headers=student_headers)).json()
    payload = await _payload(client, student_headers)
    r = await client.post("/boarding/scan", json=payload, headers=student_headers)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["status"] == "boarded" and b["boarding_id"] == f"BRD-{payload['trip_id']}-U-S0001"
    assert (b["bus_id"], b["trip_id"], b["stop_id"]) == ("B05", payload["trip_id"], "S27")
    assert b["occupancy"] == before["occupancy"] + 1 and b["capacity"] == 50
    assert b["available_seats"] == 50 - b["occupancy"]
    assert b["occupancy_percentage"] == round(100 * b["occupancy"] / 50)

    again = (await client.post("/boarding/scan", json=payload, headers=student_headers)).json()
    assert again["status"] == "already_boarded" and again["occupancy"] == b["occupancy"]
    assert again["message"] == "You have already boarded this trip."

    occ = (await client.get("/buses/B05/occupancy", headers=student_headers)).json()
    assert occ["occupancy"] == b["occupancy"] and occ["boarded"] == 1 and occ["trip_id"] == payload["trip_id"]
    assert occ["source"] == "synthetic_baseline+qr" and occ["updated_at"]
    # the EXISTING bus APIs carry the same backend numbers
    fleet = {x["id"]: x for x in (await client.get("/buses", headers=student_headers)).json()}
    live = fleet["B05"]["live"]
    assert (live["occupancy"], live["available_seats"], live["boarded_count"]) == (
        b["occupancy"],
        b["available_seats"],
        1,
    )
    arrivals = (await client.get("/students/me/arrivals", headers=student_headers)).json()
    assert arrivals["my_bus"]["occupancy"] == b["occupancy"]
    assert arrivals["my_bus"]["occupancy_percentage"] == b["occupancy_percentage"]
    me = (await client.get("/students/me/boarding", headers=student_headers)).json()
    assert me["ready"] is False and me["boarded"]["boarding_id"] == b["boarding_id"]


async def test_invalid_assignment_rejections(live_client, student_headers):
    client, container = live_client
    await advance(container, 3 * 60)
    payload = await _payload(client, student_headers)
    wrong_bus = await client.post(
        "/boarding/scan", json={**payload, "bus_id": "B06"}, headers=student_headers
    )
    assert wrong_bus.status_code == 403 and wrong_bus.json()["error"]["code"] == "wrong_bus"
    other = await client.post(
        "/boarding/scan", json={**payload, "student_id": "U-S0002"}, headers=student_headers
    )
    assert other.status_code == 403 and other.json()["error"]["code"] == "invalid_student"
    stop = await client.post("/boarding/scan", json={**payload, "stop_id": "S08"}, headers=student_headers)
    assert stop.status_code == 422 and stop.json()["error"]["code"] == "invalid_stop"
    unassigned = await login(client, "student025@campusride.demo")
    r = await client.post("/boarding/scan", json={**payload, "student_id": "U-S0025"}, headers=unassigned)
    assert r.status_code == 409 and r.json()["error"]["code"] == "unassigned"
    admin = await login(client, "admin1@campusride.demo")
    r = await client.post("/boarding/scan", json=payload, headers=admin)
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_a_student"
    bad = await client.post("/boarding/scan", json={"student_id": "U-S0001"}, headers=student_headers)
    assert bad.status_code == 422  # malformed QR payload


async def test_inactive_trip_and_bus_full(live_client, student_headers):
    client, container = live_client
    await advance(container, 3 * 60)
    payload = await _payload(client, student_headers)
    state = await container.repos.bus_states.get("B05")
    await container.repos.bus_states.upsert(
        state.model_copy(update={"occupancy_baseline": 50, "occupancy": 50})
    )
    full = await client.post("/boarding/scan", json=payload, headers=student_headers)
    assert full.status_code == 409 and full.json()["error"]["code"] == "bus_full"
    me = (await client.get("/students/me/boarding", headers=student_headers)).json()
    assert me["ready"] is False and me["reason_code"] == "bus_full"
    await container.repos.trips.set_status(payload["trip_id"], TripStatus.COMPLETED, container.clock.now())
    inactive = await client.post("/boarding/scan", json=payload, headers=student_headers)
    assert inactive.status_code == 409 and inactive.json()["error"]["code"] == "trip_inactive"


async def test_occupancy_endpoint(live_client, student_headers):
    client, _ = live_client
    r = await client.get("/buses/B05/occupancy", headers=student_headers)
    assert r.status_code == 200
    o = r.json()
    assert set(o) >= {
        "bus_id",
        "trip_id",
        "occupancy",
        "capacity",
        "available_seats",
        "occupancy_percentage",
        "source",
        "updated_at",
    }
    assert (await client.get("/buses/B99/occupancy", headers=student_headers)).status_code == 404
    assert (await client.get("/buses/B05/occupancy")).status_code == 401


async def test_trip_boarding_admin_and_student_privacy(live_client, student_headers):
    client, container = live_client
    await advance(container, 3 * 60)
    payload = await _payload(client, student_headers)
    await client.post("/boarding/scan", json=payload, headers=student_headers)
    path = f"/trips/{payload['trip_id']}/boarding"

    admin = await login(client, "admin1@campusride.demo")
    a = (await client.get(path, headers=admin)).json()
    assert a["visibility"] == "all" and a["total_boarded"] == 1
    assert a["events"][0]["student_id"] == "U-S0001" and a["events"][0]["stop_id"] == "S27"

    other = await login(client, "student002@campusride.demo")
    o = (await client.get(path, headers=other)).json()
    assert o["visibility"] == "own" and o["events"] == [] and o["total_boarded"] == 1  # no names leak
    mine = (await client.get(path, headers=student_headers)).json()
    assert [e["student_id"] for e in mine["events"]] == ["U-S0001"]
    assert (await client.get("/trips/T-NOPE/boarding", headers=admin)).status_code == 404
    assert (await client.get(path)).status_code == 401


async def test_my_boarding_unassigned_and_roles(live_client):
    client, _ = live_client
    new = await login(client, "student025@campusride.demo")
    body = (await client.get("/students/me/boarding", headers=new)).json()
    assert body["status"] == "unassigned" and body["ready"] is False and body["trip_id"] is None
    admin = await login(client, "admin1@campusride.demo")
    assert (await client.get("/students/me/boarding", headers=admin)).status_code == 403
