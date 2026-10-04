"""MISSED_BUS and driver-controlled buses (Feature 11 × Feature 12).

A driver-controlled bus waits at its trip's first stop until the driver presses Start
Trip; until then its trip is SCHEDULED. A student cannot have missed a bus whose trip has
not started, so MISSED_BUS is only raised for trips whose stored status is ACTIVE or
COMPLETED — read fresh, so a decision computed from an outdated bus state (e.g. a sweep
straddling a simulator reset, which replays the same trip ids) can't raise it either.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.main import create_app
from app.models.common import AlertType, TripStatus
from app.services.alert_service import AlertSpec, Recipient, deduplicate_key
from tests.conftest import SEED, SERVICE_DATE, advance, login
from tests.wsclient import WsTestClient, of_type

DRIVER = "driver07@campusride.demo"
ADMIN = "admin1@campusride.demo"


def _settings(driver_buses: str) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        seed=SEED,
        mock_token_secret="test-secret",
        sim_driver_controlled_buses=driver_buses,
        ws_flush_interval_s=3600,
    )


@pytest.fixture
def settings() -> Settings:  # B07 is driver-controlled (any bus in the setting behaves the same)
    return _settings("B07")


async def _missed(container, bus_id: str, *, active: bool | None = True):
    return [
        a
        for a in await container.repos.alerts.list()
        if a.type is AlertType.MISSED_BUS and a.bus_id == bus_id and (active is None or a.active is active)
    ]


async def _riders(container, bus_id: str) -> list[str]:
    return sorted(a.id for a in await container.repos.student_assignments.for_bus(bus_id))


async def test_waiting_for_the_driver_never_raises_missed(live_client):
    _, container = live_client
    mon = container.alert_monitor()
    trip_id = (await container.repos.bus_states.get("B07")).trip_id
    for _ in range(9):  # 90 simulated minutes, far past the scheduled 07:15 departure
        await advance(container, 10 * 60)
        await mon.sweep()
    state = await container.repos.bus_states.get("B07")
    assert state.status.value == "at_depot" and state.trip_id == trip_id
    assert (await container.repos.trips.get(trip_id)).status is TripStatus.SCHEDULED
    assert await _missed(container, "B07", active=None) == []


async def test_outdated_missed_decision_after_reset_is_ignored(live_client):
    """The live-demo bug: a sweep computed while B07's stopped trip was COMPLETED finishes
    after a reset replayed the same trip (SCHEDULED again, bus waiting for its driver)."""
    client, container = live_client
    d, admin = await login(client, DRIVER), await login(client, ADMIN)
    await client.post("/driver/trip/start", headers=d)
    await advance(container, 4 * 60)
    await client.post("/driver/trip/stop", headers=d)
    await advance(container, 60)
    stale = await container.recovery().for_students(await _riders(container, "B07"))
    assert any(r.commute.result.decision == "MISSED" for r in stale)  # from the COMPLETED state
    assert (await client.post("/sim/reset", headers=admin)).status_code == 200
    for r in stale:  # the sweep's second half runs after the reset
        await container.alerts().evaluate_student(r)
    state = await container.repos.bus_states.get("B07")
    assert state.status.value == "at_depot"
    assert (await container.repos.trips.get(state.trip_id)).status is TripStatus.SCHEDULED
    assert await _missed(container, "B07") == []
    await advance(container, 5 * 60)
    await container.alert_monitor().sweep()
    assert await _missed(container, "B07") == []


async def test_an_alert_left_from_an_outdated_state_is_resolved(live_client):
    _, container = live_client
    svc, mon = container.alerts(), container.alert_monitor()
    trip_id = (await container.repos.bus_states.get("B07")).trip_id
    rider = (await _riders(container, "B07"))[0]
    a = await svc.create_alert(
        AlertSpec(
            AlertType.MISSED_BUS,
            Recipient(rider),
            "You missed your assigned bus B07.",
            container.clock.now(),
            "B07",
            trip_id,
            "R4",
        )
    )
    assert a is not None and a.active
    await advance(container, 60)
    await mon.sweep()  # trip still SCHEDULED (driver hasn't started) → condition false → resolve
    fresh = await container.repos.alerts.get(a.id)
    assert fresh.active is False and fresh.resolved_at is not None
    assert await container.repos.alerts.count_series(a.dedup_key) == 1  # resolved, not duplicated


async def test_after_start_a_genuinely_missed_bus_still_alerts_once(live_client):
    client, container = live_client
    mon = container.alert_monitor()
    d = await login(client, DRIVER)
    trip_id = (await client.post("/driver/trip/start", headers=d)).json()["trip"]["id"]
    await advance(container, 4 * 60)  # the bus has passed the first stops (nobody boarded)
    await mon.sweep()
    missed = await _missed(container, "B07")
    assert missed, "students at stops the started bus already passed must get MISSED_BUS"
    assert {a.trip_id for a in missed} == {trip_id}
    assert (await container.repos.trips.get(trip_id)).status is TripStatus.ACTIVE
    for a in missed:
        assert a.payload["reason"] and a.body.startswith("You missed your assigned bus B07")
    # idempotent: more sweeps never add a second alert for the same student + trip
    await advance(container, 60)
    await mon.sweep()
    await mon.sweep()
    for a in missed:
        assert await container.repos.alerts.count_series(a.dedup_key) == 1
    assert len(await _missed(container, "B07")) >= len(missed)


async def test_stopping_early_still_reports_missed_for_unreached_students(live_client):
    """Existing Feature 11 behaviour kept: a completed (stopped) trip that never reached a
    student's stop is MISSED for them (the trip did start)."""
    client, container = live_client
    d = await login(client, DRIVER)
    trip_id = (await client.post("/driver/trip/start", headers=d)).json()["trip"]["id"]
    await advance(container, 3 * 60)
    await client.post("/driver/trip/stop", headers=d)
    await advance(container, 30)
    await container.alert_monitor().sweep()
    assert (await container.repos.trips.get(trip_id)).status is TripStatus.COMPLETED
    assert await _missed(container, "B07")


async def test_realtime_stream_carries_no_false_missed(live_client):
    client, container = live_client
    rider = (await _riders(container, "B07"))[0]
    user = await container.repos.users.get(rider)
    sock = await WsTestClient(create_app(container=container)).connect()
    try:
        await sock.auth(await login(client, user.email))
        for _ in range(6):
            await advance(container, 10 * 60)
            await container.alert_monitor().sweep()
        msgs = await sock.drain()
        assert [m for m in of_type(msgs, "alert.created") if m["data"]["type"] == "MISSED_BUS"] == []
    finally:
        await sock.close()
        await container.realtime().shutdown()


class TestAutomaticBuses:
    """With no driver-controlled buses the morning runs exactly as before."""

    @pytest.fixture
    def settings(self) -> Settings:
        return _settings("")

    async def test_missed_alerts_only_for_started_trips_and_unchanged_semantics(self, live_client):
        _, container = live_client
        mon = container.alert_monitor()
        for _ in range(8):
            await advance(container, 5 * 60)
            await mon.sweep()
        missed = [a for a in await container.repos.alerts.list() if a.type is AlertType.MISSED_BUS]
        assert missed, "automatic buses still produce genuine MISSED_BUS alerts"
        trips = {t.id: t for t in await container.repos.trips.on_date(SERVICE_DATE)}
        for a in missed:
            assert trips[a.trip_id].status in (TripStatus.ACTIVE, TripStatus.COMPLETED)
            key = deduplicate_key(AlertType.MISSED_BUS, Recipient(a.audience.user_id), a.bus_id, a.trip_id)
            assert key == a.dedup_key and await container.repos.alerts.count_series(key) == 1
