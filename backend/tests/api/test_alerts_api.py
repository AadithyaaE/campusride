"""GET /alerts and PATCH /alerts/{id}/read (Feature 11)."""

from __future__ import annotations

from app.models.common import AlertType
from app.services.alert_service import ADMINS, AlertSpec, Recipient
from tests.conftest import login
from tests.unit.test_eta import MIDDAY

FIELDS = {
    "alert_id",
    "type",
    "title",
    "message",
    "bus_id",
    "student_id",
    "admin_id",
    "severity",
    "timestamp",
    "read",
    "resolved_at",
    "active",
}


async def _seed(container):
    s = container.alerts()
    mine = await s.create_alert(
        AlertSpec(
            AlertType.BUS_APPROACHING,
            Recipient("U-S0001"),
            "Bus B05 reaches your stop in 3 minutes.",
            MIDDAY,
            "B05",
            "T1",
            "R3",
        )
    )
    old = await s.create_alert(
        AlertSpec(
            AlertType.BUS_DELAYED,
            Recipient("U-S0001"),
            "Bus B05 is running 8 minutes late.",
            MIDDAY,
            "B05",
            "T0",
            "R3",
        )
    )
    await s.resolve_alert(old.dedup_key, MIDDAY)
    theirs = await s.create_alert(
        AlertSpec(
            AlertType.MISSED_BUS,
            Recipient("U-S0002"),
            "You missed your assigned bus B06.",
            MIDDAY,
            "B06",
            "T2",
            "R3",
        )
    )
    fleet = await s.create_alert(
        AlertSpec(
            AlertType.CAPACITY_WARNING,
            ADMINS,
            "Bus B05 is 84% full with 8 seats remaining.",
            MIDDAY,
            "B05",
            "T1",
            "R3",
        )
    )
    return mine, old, theirs, fleet


async def test_requires_authentication(client):
    assert (await client.get("/alerts")).status_code == 401
    assert (await client.patch("/alerts/X/read")).status_code == 401


async def test_empty_list(client, student_headers):
    r = await client.get("/alerts", headers=student_headers)
    assert r.status_code == 200 and r.json() == []


async def test_student_sees_only_own_alerts_with_filters(client, container, student_headers):
    mine, old, _theirs, _fleet = await _seed(container)
    body = (await client.get("/alerts", headers=student_headers)).json()
    assert [a["alert_id"] for a in body] and {a["alert_id"] for a in body} == {mine.id, old.id}
    a = next(x for x in body if x["alert_id"] == mine.id)
    assert FIELDS <= set(a)
    assert (a["type"], a["title"], a["severity"], a["student_id"], a["recipient"], a["read"]) == (
        "BUS_APPROACHING",
        "BUS APPROACHING",
        "info",
        "U-S0001",
        "student",
        False,
    )
    assert a["message"] == "Bus B05 reaches your stop in 3 minutes." and a["bus_id"] == "B05"
    active = (await client.get("/alerts", params={"active": True}, headers=student_headers)).json()
    assert [x["alert_id"] for x in active] == [mine.id]
    resolved = (await client.get("/alerts", params={"active": False}, headers=student_headers)).json()
    assert [x["alert_id"] for x in resolved] == [old.id] and resolved[0]["resolved_at"]
    limited = (await client.get("/alerts", params={"limit": 1}, headers=student_headers)).json()
    assert len(limited) == 1


async def test_mark_read_ownership_and_idempotency(client, container, student_headers):
    mine, _, theirs, fleet = await _seed(container)
    r = await client.patch(f"/alerts/{mine.id}/read", headers=student_headers)
    assert r.status_code == 200 and r.json()["read"] is True
    again = await client.patch(f"/alerts/{mine.id}/read", headers=student_headers)
    assert again.status_code == 200 and again.json()["read"] is True  # idempotent
    unread = (await client.get("/alerts", params={"unread": True}, headers=student_headers)).json()
    assert mine.id not in {x["alert_id"] for x in unread}
    assert (await client.patch(f"/alerts/{theirs.id}/read", headers=student_headers)).status_code == 404
    assert (await client.patch(f"/alerts/{fleet.id}/read", headers=student_headers)).status_code == 404
    assert (await client.patch("/alerts/ALT-NOPE/read", headers=student_headers)).status_code == 404
    other = await login(client, "student002@campusride.demo")
    assert (await client.patch(f"/alerts/{mine.id}/read", headers=other)).status_code == 404


async def test_admin_sees_fleet_alerts_only(client, container):
    mine, _, _theirs, fleet = await _seed(container)
    admin = await login(client, "admin1@campusride.demo")
    body = (await client.get("/alerts", headers=admin)).json()
    assert [a["alert_id"] for a in body] == [fleet.id]  # no students' personal alerts
    assert body[0]["recipient"] == "admin" and body[0]["student_id"] is None
    r = await client.patch(f"/alerts/{fleet.id}/read", headers=admin)
    assert r.status_code == 200 and r.json()["read"] is True
    assert (await client.patch(f"/alerts/{mine.id}/read", headers=admin)).status_code == 404


async def test_drivers_have_no_in_app_alerts(client):
    driver = await login(client, "driver05@campusride.demo")
    assert (await client.get("/alerts", headers=driver)).status_code == 403
