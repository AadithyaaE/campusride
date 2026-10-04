"""Feature 13 — transport admin dashboard: /admin/overview, /fleet, /routes, /schedule, /analytics.

Everything is read from the SAME backend state the Student and Driver apps use. B07
(driver D07) is driver-controlled in this module; every other bus runs the automatic
demo schedule.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.config import Settings
from app.models import BusState, GeoPoint
from app.models.common import BusStatus, TripStatus
from app.models.events import BusStateUpdated
from app.services.admin_service import synthetic_analytics
from app.services.ridership import RidershipLedger
from tests.conftest import SEED, SERVICE_DATE, advance, login

ADMIN = "admin1@campusride.demo"
DRIVER = "driver07@campusride.demo"
ENDPOINTS = ["/admin/overview", "/admin/fleet", "/admin/routes", "/admin/schedule", "/admin/analytics"]


@pytest.fixture
def settings() -> Settings:  # overrides the session fixture for this module only
    return Settings(
        _env_file=None,
        app_env="test",
        seed=SEED,
        mock_token_secret="test-secret",
        sim_driver_controlled_buses="B07",
    )


async def _get(client, path, headers, **params):
    r = await client.get(path, headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def _fleet(client, headers, **params) -> dict[str, dict]:
    return {b["bus_id"]: b for b in (await _get(client, "/admin/fleet", headers, **params))["buses"]}


async def _board_one(client, container, bus_id: str) -> str:
    """QR-board the first assigned student of ``bus_id`` whose stop is still ahead (Feature 8)."""
    for a in sorted(await container.repos.student_assignments.for_bus(bus_id), key=lambda a: a.id):
        user = await container.repos.users.get(a.id)
        headers = await login(client, user.email)
        me = (await client.get("/students/me/boarding", headers=headers)).json()
        if not me["ready"]:
            continue
        payload = {k: me[k] for k in ("student_id", "bus_id", "trip_id")} | {
            "timestamp": container.clock.now().isoformat()
        }
        r = await client.post("/boarding/scan", json=payload, headers=headers)
        assert r.status_code == 200, r.text
        return a.id
    pytest.fail(f"no boardable student on {bus_id}")


# ----------------------------------------------------------------------------- authorization


async def test_admin_only(live_client, student_headers):
    client, _ = live_client
    admin = await login(client, ADMIN)
    driver = await login(client, DRIVER)
    for path in ENDPOINTS:
        assert (await client.get(path)).status_code == 401, path
        r = await client.get(path, headers=student_headers)
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden", path
        assert (await client.get(path, headers=driver)).status_code == 403, path
        assert (await client.get(path, headers=admin)).status_code == 200, path


# ----------------------------------------------------------------------------- overview / KPIs


async def test_overview_kpis_match_backend_state(live_client):
    client, container = live_client
    admin = await login(client, ADMIN)
    await advance(container, 6 * 60)
    o = await _get(client, "/admin/overview", admin)
    repos = container.repos
    trips = await repos.trips.on_date(SERVICE_DATE)
    assert o["total_buses"] == len(await repos.buses.list()) == 12
    assert o["buses_in_service"] == 12
    assert o["students"] == await repos.users.count(filter={"role": "student"}) > 0
    assert o["assigned_students"] == await repos.student_assignments.count()
    assert o["trips_today"]["total"] == len(trips)
    active = [t for t in trips if t.status is TripStatus.ACTIVE]
    assert o["active_trips"] == o["trips_today"]["active"] == len(active) > 0
    assert o["service_date"] == SERVICE_DATE.isoformat()
    fleet = await _fleet(client, admin)
    assert o["buses_on_trip"] == sum(
        b["operational_status"] in ("active", "delayed", "deviated", "breakdown") for b in fleet.values()
    )
    assert o["delayed_buses"] == sum(b["is_delayed"] for b in fleet.values())
    assert o["passengers_method"]


async def test_passengers_today_is_the_sum_of_trip_peaks(live_client):
    client, container = live_client
    admin = await login(client, ADMIN)
    assert (await _get(client, "/admin/overview", admin))["passengers_today"] == 0  # nobody departed
    await advance(container, 10 * 60)
    o = await _get(client, "/admin/overview", admin)
    trips = await container.repos.trips.on_date(SERVICE_DATE)
    ledger = container.ridership()
    started = [t for t in trips if t.status in (TripStatus.ACTIVE, TripStatus.COMPLETED)]
    assert o["passengers_today"] == sum(ledger.peak(t.id) for t in started) > 0
    # a running trip's peak is never below what is on board right now
    for t in started:
        s = await container.repos.bus_states.get(t.bus_id)
        if s.trip_id == t.id and s.status in (BusStatus.EN_ROUTE, BusStatus.DWELLING):
            assert ledger.peak(t.id) >= s.occupancy


async def test_ridership_ledger_restarts_a_trip_after_a_reset(clock):
    ledger = RidershipLedger()
    base = BusState(
        _id="B01",
        trip_id="T1",
        route_id="R1",
        ts=clock.now(),
        last_seen=clock.now(),
        location=GeoPoint.of(80.2, 12.9),
        status=BusStatus.EN_ROUTE,
        occupancy=30,
    )
    await ledger.on_bus_state(BusStateUpdated(ts=base.ts, state=base))
    later = base.model_copy(update={"ts": clock.now() + timedelta(minutes=10), "occupancy": 12})
    await ledger.on_bus_state(BusStateUpdated(ts=later.ts, state=later))
    assert ledger.peak("T1") == 30  # the peak is kept while riders alight
    waiting = base.model_copy(update={"status": BusStatus.AT_DEPOT, "occupancy": 45})
    await ledger.on_bus_state(BusStateUpdated(ts=waiting.ts, state=waiting))  # clock went back
    assert ledger.peak("T1") == 0  # restarted; not counted until the bus runs
    assert ledger.peak("unknown") == 0


# ----------------------------------------------------------------------------- fleet


async def test_fleet_rows_reuse_backend_values(live_client):
    client, container = live_client
    admin = await login(client, ADMIN)
    await advance(container, 6 * 60)
    body = await _get(client, "/admin/fleet", admin)
    assert body["total"] == 12 and len(body["buses"]) == 12
    assert {o["value"] for o in body["options"]["routes"]} == {"R1", "R2", "R3", "R4", "R5", "R6"}
    assert len(body["options"]["buses"]) == 12
    assert "delayed" in {o["value"] for o in body["options"]["statuses"]}
    buses = {b["id"]: b for b in await _get(client, "/buses", admin)}
    checked = 0
    for row in body["buses"]:
        live = buses[row["bus_id"]]["live"]
        if live is None:
            continue
        assert row["occupancy"] == live["occupancy"]
        assert row["occupancy_percentage"] == live["occupancy_percentage"]
        assert row["available_seats"] == live["available_seats"]
        assert row["route_status"] == live["route_status"]
        assert row["speed_kmh"] == round(live["speed_mps"] * 3.6)
        assert row["location"] == {
            "lat": live["location"]["coordinates"][1],
            "lon": live["location"]["coordinates"][0],
        }
        assert row["is_delayed"] == (live["schedule_status"] == "delayed")
        assert row["gps"] in ("LIVE", "STALE")
        if row["operational_status"] == "active" and row["next_stop"]:
            eta = await _get(client, f"/buses/{row['bus_id']}/eta", admin, stop_id=row["next_stop"]["id"])
            assert row["eta_next_stop_min"] == eta["eta_minutes"]  # the Feature 5 ETA, not a new one
            assert row["eta_status"] == eta["status"]
            checked += 1
    assert checked > 0
    b05 = next(r for r in body["buses"] if r["bus_id"] == "B05")
    assert b05["driver"]["id"] == "D05" and b05["route_name"] and b05["route_color"].startswith("#")
    assert b05["direction_label"] and b05["current_stop"]["name"]


async def test_fleet_filters(live_client):
    client, container = live_client
    admin = await login(client, ADMIN)
    await advance(container, 6 * 60)
    r1 = await _get(client, "/admin/fleet", admin, route_id="R1")
    assert r1["total"] == 12 and r1["filters"]["route_id"] == "R1"
    assert {b["bus_id"] for b in r1["buses"]} == {"B01", "B02"}
    one = await _get(client, "/admin/fleet", admin, bus_id="B05")
    assert [b["bus_id"] for b in one["buses"]] == ["B05"]
    everything = await _fleet(client, admin)
    for status in ("active", "waiting", "idle"):
        rows = (await _get(client, "/admin/fleet", admin, status=status))["buses"]
        assert {b["bus_id"] for b in rows} == {
            k for k, v in everything.items() if v["operational_status"] == status
        }
    assert (await _get(client, "/admin/fleet", admin, status="waiting"))["buses"]  # B07 waits for D07
    combined = await _get(client, "/admin/fleet", admin, route_id="R4", bus_id="B07")
    assert [b["bus_id"] for b in combined["buses"]] == ["B07"]
    assert (await _get(client, "/admin/fleet", admin, route_id="R9"))["buses"] == []
    bad = await client.get("/admin/fleet", headers=admin, params={"status": "flying"})
    assert bad.status_code == 422


# ----------------------------------------------------------------------------- feature integrations


async def test_route_deviation_and_alert_reach_the_admin_views(live_client):
    """Feature 10 deviation + Feature 11 alert, as the admin dashboard sees them."""
    client, container = live_client
    admin = await login(client, ADMIN)
    await advance(container, 5 * 60)
    r = await client.post("/sim/route-deviation", json={"mode": "major", "bus_id": "B05"}, headers=admin)
    assert r.status_code == 200
    await advance(container, 30)
    b05 = (await _fleet(client, admin))["B05"]
    rs = await _get(client, "/buses/B05/route-status", admin)
    assert b05["route_status"] == rs["route_status"] == "MAJOR_DEVIATION"
    assert b05["operational_status"] == "deviated"
    assert b05["deviation_distance_m"] == pytest.approx(rs["deviation_distance_m"])
    assert any(a["type"] == "ROUTE_DEVIATION" and a["severity"] == "critical" for a in b05["active_alerts"])
    o = await _get(client, "/admin/overview", admin)
    assert o["deviated_buses"] >= 1 and o["major_deviations"] >= 1 and o["alerts"]["critical"] >= 1
    alerts = await _get(client, "/alerts", admin, active="true")
    assert o["alerts"]["active"] == len(alerts)
    assert (
        "B05"
        in next(x for x in await _get(client, "/admin/routes", admin) if x["id"] == "R3")["deviated_buses"]
    )
    assert (await _get(client, "/admin/fleet", admin, status="deviated"))["buses"][0]["bus_id"] == "B05"

    await client.post("/sim/route-deviation", json={"mode": "normal", "bus_id": "B05"}, headers=admin)
    await advance(container, 30)
    back = (await _fleet(client, admin))["B05"]
    assert back["route_status"] == "NORMAL" and back["operational_status"] != "deviated"
    assert not any(a["type"] == "ROUTE_DEVIATION" for a in back["active_alerts"])  # resolved


async def test_delay_uses_the_tracking_rule_and_raises_the_existing_alert(live_client):
    client, container = live_client
    admin = await login(client, ADMIN)
    await advance(container, 6 * 60)
    s = await container.repos.bus_states.get("B05")
    assert s.status in (BusStatus.EN_ROUTE, BusStatus.DWELLING)
    late = s.model_copy(update={"delay_s": 8 * 60})
    await container.repos.bus_states.upsert(late)
    await container.events.publish(BusStateUpdated(ts=late.ts, state=late))  # → AlertService
    b05 = (await _fleet(client, admin))["B05"]
    assert b05["is_delayed"] is True and b05["operational_status"] == "delayed"
    assert b05["delay_s"] == 480 and b05["delay_min"] == 8
    assert any(a["type"] == "BUS_DELAYED" for a in b05["active_alerts"])
    assert (await _get(client, "/admin/overview", admin))["delayed_buses"] >= 1
    assert "B05" in [
        b["bus_id"] for b in (await _get(client, "/admin/fleet", admin, status="delayed"))["buses"]
    ]
    sched = await _get(client, "/admin/schedule", admin)
    assert next(t for t in sched["trips"] if t["trip_id"] == s.trip_id)["delay_min"] == 8


async def test_occupancy_and_crowding_come_from_feature_8(live_client):
    client, container = live_client
    admin = await login(client, ADMIN)
    d = await login(client, DRIVER)
    await client.post("/driver/trip/start", headers=d)
    await advance(container, 60)
    before = (await _fleet(client, admin))["B07"]
    await _board_one(client, container, "B07")
    after = (await _fleet(client, admin))["B07"]
    occ = await _get(client, "/buses/B07/occupancy", admin)
    assert after["occupancy"] == occ["occupancy"] == min(50, before["occupancy"] + 1)
    assert after["available_seats"] == occ["available_seats"]
    assert after["boarded_count"] == before["boarded_count"] + 1
    assert (await _get(client, "/admin/overview", admin))["qr_boardings_today"] == 1
    slots = (await _get(client, "/admin/analytics", admin))["live"]["qr_boardings_by_slot"]
    assert sum(x["value"] for x in slots) == 1
    # crowding bands are the Feature 6 ones (<60 Low · 60–79 Medium · ≥80 High)
    s = await container.repos.bus_states.get("B07")
    for occupancy, band in ((29, "Low"), (30, "Medium"), (39, "Medium"), (40, "High")):
        await container.repos.bus_states.upsert(s.model_copy(update={"occupancy": occupancy}))
        assert (await _fleet(client, admin, bus_id="B07"))["B07"]["crowding"] == band


# ----------------------------------------------------------------------------- routes / schedule / analytics


async def test_routes_are_read_only_summaries_of_existing_data(live_client):
    client, container = live_client
    admin = await login(client, ADMIN)
    await advance(container, 6 * 60)
    routes = await _get(client, "/admin/routes", admin)
    assert [r["id"] for r in routes] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    r1 = routes[0]
    stored = await container.repos.routes.get("R1")
    assert r1["length_km"] == round(stored.length_m / 1000, 1)
    assert [d["variant_id"] for d in r1["directions"]] == ["R1", "R1-E"]
    assert r1["directions"][0]["stop_count"] == len(stored.directions[0].stops)
    assert r1["assigned_buses"] == ["B01", "B02"]
    assert sum(r["trips_today"]["total"] for r in routes) == len(
        await container.repos.trips.on_date(SERVICE_DATE)
    )
    fleet = await _fleet(client, admin)
    for r in routes:
        assert set(r["active_buses"]) <= set(r["assigned_buses"])
        for b in r["active_buses"]:
            assert fleet[b]["operational_status"] in ("active", "delayed", "deviated", "breakdown")
    # no route mutation API exists
    assert (await client.post("/admin/routes", headers=admin, json={})).status_code == 405


async def test_schedule_lists_todays_trips(live_client):
    client, container = live_client
    admin = await login(client, ADMIN)
    body = await _get(client, "/admin/schedule", admin)
    trips = await container.repos.trips.on_date(SERVICE_DATE)
    assert body["service_date"] == SERVICE_DATE.isoformat() and len(body["trips"]) == len(trips)
    deps = [t["scheduled_departure"] for t in body["trips"]]
    assert deps == sorted(deps)
    first = body["trips"][0]
    assert first["scheduled_arrival"] > first["scheduled_departure"]
    assert first["driver"]["name"] and first["reg_no"].startswith("TN")
    assert first["direction_label"] and first["first_stop"] and first["last_stop"]
    r4 = await _get(client, "/admin/schedule", admin, route_id="R4")
    assert r4["trips"] and {t["route_id"] for t in r4["trips"]} == {"R4"}
    assert {t["bus_id"] for t in r4["trips"]} >= {"B07"}


async def test_analytics_live_and_synthetic_are_separate(live_client):
    client, container = live_client
    admin = await login(client, ADMIN)
    await advance(container, 10 * 60)
    a = await _get(client, "/admin/analytics", admin)
    o = await _get(client, "/admin/overview", admin)
    live = a["live"]
    assert sum(x["value"] for x in live["passengers_per_route"]) == o["passengers_today"]
    assert live["trips_today"] == o["trips_today"]
    assert sum(x["value"] for x in live["trips_by_departure_hour"]) == o["trips_today"]["total"]
    fleet = await _fleet(client, admin)
    for bar in live["occupancy_by_bus"]:
        assert bar["occupancy_percentage"] == fleet[bar["bus_id"]]["occupancy_percentage"]
    delays = [
        b["delay_s"] for b in fleet.values() if b["operational_status"] in ("active", "delayed", "deviated")
    ]
    assert live["average_delay"]["buses_measured"] == len(delays)
    syn = a["synthetic"]
    assert syn["synthetic"] is True and syn["label"] == "Synthetic demo data" and syn["seed"] == SEED
    assert len(syn["daily_passengers"]) == 7 and len(syn["average_delay_by_day"]) == 7
    assert syn["peak_boarding_by_hour"] and syn["passengers_per_route_weekly_avg"]
    # deterministic: same seed + date → same numbers; across polls too
    assert (await _get(client, "/admin/analytics", admin))["synthetic"] == syn
    routes = {r.id: r for r in await container.repos.routes.list()}
    again = synthetic_analytics(SEED, SERVICE_DATE, routes).model_dump(mode="json")
    assert again == syn
    other = synthetic_analytics(SEED + 1, SERVICE_DATE, routes).model_dump(mode="json")
    assert other["daily_passengers"] != syn["daily_passengers"]
    assert synthetic_analytics(SEED, date(2026, 10, 6), routes).daily_passengers[0].key == "2026-09-29"


# ----------------------------------------------------------------------------- THE integration test


async def test_admin_sees_the_same_state_as_driver_and_student(live_client, student_headers):
    """Driver 07 starts → the admin dashboard follows the SAME backend state → driver stops."""
    client, container = live_client
    admin = await login(client, ADMIN)
    d = await login(client, DRIVER)
    before = await _get(client, "/admin/overview", admin)
    assert (await _fleet(client, admin))["B07"]["operational_status"] == "waiting"

    # 1–2. driver starts; backend marks the trip ACTIVE
    started = (await client.post("/driver/trip/start", headers=d)).json()
    trip_id = started["trip"]["id"]
    assert (await container.repos.trips.get(trip_id)).status is TripStatus.ACTIVE
    await advance(container, 4 * 60)

    # 3. overview reflects the active trip
    o = await _get(client, "/admin/overview", admin)
    assert o["active_trips"] == len(
        [t for t in await container.repos.trips.on_date(SERVICE_DATE) if t.status is TripStatus.ACTIVE]
    )
    assert o["active_trips"] >= before["active_trips"] + 1 or before["active_trips"] > 0

    # 4–9. fleet shows B07 active with position, speed, occupancy, ETA and route status
    b07 = (await _fleet(client, admin))["B07"]
    state = await container.repos.bus_states.get("B07")
    me = (await client.get("/driver/me", headers=d)).json()
    student_view = {b["id"]: b for b in (await client.get("/buses", headers=student_headers)).json()}["B07"]
    assert b07["trip_id"] == trip_id == me["trip"]["id"] == student_view["live"]["trip_id"]
    assert b07["trip_status"] == "active"
    assert b07["operational_status"] in ("active", "delayed")
    assert b07["location"] == me["live"]["location"]
    assert b07["speed_kmh"] == me["live"]["speed_kmh"] == round(state.speed_mps * 3.6)
    assert b07["occupancy"] == me["live"]["occupancy"] == student_view["live"]["occupancy"]
    assert b07["capacity"] == 50 and b07["occupancy_percentage"] is not None
    assert b07["next_stop"]["id"] == state.next_stop_id
    assert b07["eta_next_stop_min"] is not None and b07["eta_status"] in ("predicted", "at_stop")
    assert b07["route_status"] == "NORMAL" and b07["gps"] == "LIVE"
    assert b07["driver"] == {"id": "D07", "name": "Arun Kumar"}
    sched = {t["trip_id"]: t for t in (await _get(client, "/admin/schedule", admin))["trips"]}
    assert sched[trip_id]["status"] == "active" and sched[trip_id]["actual_start"]

    # 10–11. driver stops → admin shows the finalized trip
    assert (await client.post("/driver/trip/stop", headers=d)).status_code == 200
    done = (await _fleet(client, admin))["B07"]
    assert done["operational_status"] == "completed" and done["trip_status"] == "completed"
    assert done["bus_status"] == "completed" and done["eta_next_stop_min"] is None
    sched = {t["trip_id"]: t for t in (await _get(client, "/admin/schedule", admin))["trips"]}
    assert sched[trip_id]["status"] == "completed" and sched[trip_id]["actual_end"]
    final = await _get(client, "/admin/overview", admin)
    assert final["trips_today"]["completed"] >= 1
    assert final["passengers_today"] >= container.ridership().peak(trip_id) > 0
