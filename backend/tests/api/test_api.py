"""Phase 1 REST API against in-memory repositories."""

from __future__ import annotations

import httpx

from tests.conftest import login


async def test_health_is_public_and_reports_sim_clock(client: httpx.AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["db"] == "not_configured"
    assert body["clock"]["mode"] == "sim"
    assert body["clock"]["local_now"].startswith("2026-10-05T07:15:00+05:30")


async def test_mock_login_and_me(client: httpx.AsyncClient):
    r = await client.post("/auth/mock-login", json={"email": "ADMIN1@campusride.demo"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["user"]["role"] == "admin"
    me = await client.get("/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json() == body["user"]


async def test_unknown_user_cannot_log_in(client: httpx.AsyncClient):
    r = await client.post("/auth/mock-login", json={"email": "nobody@campusride.demo"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_endpoints_require_a_token(client: httpx.AsyncClient):
    for path in ("/me", "/stops", "/routes", "/stops/S08/routes"):
        r = await client.get(path)
        assert r.status_code == 401, path
    r = await client.get("/stops", headers={"Authorization": "Bearer mock.garbage.sig"})
    assert r.status_code == 401


async def test_list_and_get_stops(client: httpx.AsyncClient, student_headers):
    r = await client.get("/stops", headers=student_headers)
    stops = r.json()
    assert len(stops) == 39
    campus = [s for s in stops if s["is_campus_terminal"]]
    assert [s["id"] for s in campus] == ["S00"]
    s08 = (await client.get("/stops/S08", headers=student_headers)).json()
    assert s08["name"] == "Medavakkam Koot Road"
    assert s08["location"]["type"] == "Point" and len(s08["location"]["coordinates"]) == 2
    missing = await client.get("/stops/S99", headers=student_headers)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"


async def test_nearby_stops(client: httpx.AsyncClient, student_headers):
    s08 = (await client.get("/stops/S08", headers=student_headers)).json()
    lng, lat = s08["location"]["coordinates"]
    r = await client.get(
        "/stops/nearby", params={"lat": lat, "lng": lng, "radius_m": 2000}, headers=student_headers
    )
    hits = r.json()
    assert hits[0]["id"] == "S08" and hits[0]["distance_m"] == 0
    assert all(h["distance_m"] <= 2000 for h in hits)
    bad = await client.get("/stops/nearby", params={"lat": 120, "lng": lng}, headers=student_headers)
    assert bad.status_code == 422


async def test_routes_serving_a_shared_stop(client: httpx.AsyncClient, student_headers):
    r = await client.get("/stops/S08/routes", headers=student_headers)
    variants = [x["variant_id"] for x in r.json()]
    assert variants == ["R1", "R1-E", "R2", "R2-E", "R5", "R5-E"]
    labels = {x["variant_id"]: x["label"] for x in r.json()}
    assert labels["R1"] == "R1 — To Campus" and labels["R1-E"] == "R1-E — From Campus"


async def test_routes_list_and_detail(client: httpx.AsyncClient, student_headers):
    routes = (await client.get("/routes", headers=student_headers)).json()
    assert [r["id"] for r in routes] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    assert all(len(r["directions"]) == 2 for r in routes)

    r1 = (await client.get("/routes/R1", headers=student_headers)).json()
    assert r1["path"]["type"] == "LineString" and len(r1["path"]["coordinates"]) > 100
    to, frm = r1["directions"]
    assert to["variant_id"] == "R1" and frm["variant_id"] == "R1-E"
    assert to["stops"][-1]["stop_id"] == "S00" and frm["stops"][0]["stop_id"] == "S00"
    assert [s["stop_id"] for s in frm["stops"]] == [s["stop_id"] for s in reversed(to["stops"])]
    assert to["stops"][0]["name"] == "Tambaram Railway Station"
    assert (await client.get("/routes/R9", headers=student_headers)).status_code == 404


async def test_bus_secrets_never_leak(client: httpx.AsyncClient):
    headers = await login(client, "admin1@campusride.demo")
    for path in ("/stops", "/routes", "/routes/R1", "/stops/S08/routes", "/me"):
        assert "qr_secret" not in (await client.get(path, headers=headers)).text


async def test_openapi_is_served(client: httpx.AsyncClient):
    r = await client.get("http://test/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/api/v1/stops/{stop_id}/routes" in paths and "/api/v1/auth/mock-login" in paths


async def test_student_sees_their_college_assigned_bus(client: httpx.AsyncClient, student_headers):
    r = await client.get("/students/me/assignment", headers=student_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "assigned" and body["student_id"] == "U-S0001"
    a = body["assignment"]
    assert set(a) == {"bus", "route", "boarding_stop", "assigned_at"}
    assert a["bus"]["id"].startswith("B") and "qr_secret" not in r.text
    assert a["route"]["direction"] == "to_campus"
    assert a["route"]["route_direction_id"] == a["route"]["route_id"]
    assert 0 <= a["boarding_stop"]["seq"] < a["boarding_stop"]["stop_count"] - 1


async def test_unassigned_student_gets_explicit_unassigned(client: httpx.AsyncClient):
    headers = await login(client, "student025@campusride.demo")
    body = (await client.get("/students/me/assignment", headers=headers)).json()
    assert body == {"student_id": "U-S0025", "status": "unassigned", "assignment": None}


async def test_assignment_is_student_only_and_read_only(client: httpx.AsyncClient, student_headers):
    assert (await client.get("/students/me/assignment")).status_code == 401
    admin = await login(client, "admin1@campusride.demo")
    assert (await client.get("/students/me/assignment", headers=admin)).status_code == 403
    for method in ("PUT", "POST", "PATCH", "DELETE"):
        r = await client.request(method, "/students/me/assignment", headers=student_headers, json={})
        assert r.status_code == 405, method


async def test_bus_fleet_list(client: httpx.AsyncClient, student_headers):
    r = await client.get("/buses", headers=student_headers)
    assert r.status_code == 200
    buses = r.json()
    assert len(buses) == 12
    assert set(buses[0]) == {"id", "reg_no", "capacity", "route_id", "status", "source", "live"}
    assert "qr_secret" not in r.text
    per_route = {}
    for b in buses:
        per_route.setdefault(b["route_id"], []).append(b["id"])
    assert all(len(v) == 2 for v in per_route.values())
    assert (await client.get("/buses")).status_code == 401
