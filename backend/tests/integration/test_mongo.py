"""MongoDB repositories, indexes and the time-series collection.

    docker compose -f infra/docker-compose.yml up -d
    pytest -m integration

Uses database ``campusride_test`` (dropped before and after each test).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import DEFAULT_TZ
from app.core.db import Collections, Database, ensure_indexes
from app.core.errors import ConflictError
from app.models import GeoPoint, Telemetry, TelemetryMeta, User
from app.models.common import BusSource, Role, TripStatus
from app.repositories.base import Repositories
from app.repositories.mongo import mongo_repositories
from app.seed import SeedBundle, persist_seed
from tests.conftest import SERVICE_DATE

pytestmark = pytest.mark.integration

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
TEST_DB = "campusride_test"


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    db = Database(MONGO_URI, TEST_DB)
    if not await db.ping():
        db.close()
        pytest.fail(
            f"MongoDB not reachable at {MONGO_URI} — "
            "start it: docker compose -f infra/docker-compose.yml up -d"
        )
    await db.client.drop_database(TEST_DB)
    await ensure_indexes(db.db, telemetry_ttl_days=30)
    yield db
    await db.client.drop_database(TEST_DB)
    db.close()


@pytest.fixture
async def repos(database: Database, bundle: SeedBundle) -> Repositories:
    r = mongo_repositories(database.db)
    await persist_seed(r, bundle, SERVICE_DATE, DEFAULT_TZ)
    return r


async def test_telemetry_is_time_series_with_ttl(database: Database):
    info = await database.db.command({"listCollections": 1, "filter": {"name": Collections.TELEMETRY}})
    coll = info["cursor"]["firstBatch"][0]
    assert coll["type"] == "timeseries"
    assert coll["options"]["timeseries"]["timeField"] == "ts"
    assert coll["options"]["timeseries"]["metaField"] == "meta"
    assert coll["options"]["expireAfterSeconds"] == 30 * 86_400


async def test_ensure_indexes_is_idempotent_and_updates_ttl(database: Database):
    await ensure_indexes(database.db, telemetry_ttl_days=30)
    await ensure_indexes(database.db, telemetry_ttl_days=7)
    info = await database.db.command({"listCollections": 1, "filter": {"name": Collections.TELEMETRY}})
    assert info["cursor"]["firstBatch"][0]["options"]["expireAfterSeconds"] == 7 * 86_400


async def test_expected_indexes_exist(database: Database):
    stops = await database.db[Collections.STOPS].index_information()
    assert stops["location_2dsphere"]["key"] == [("location", "2dsphere")]
    tele = await database.db[Collections.TELEMETRY].index_information()
    assert {"trip_ts", "bus_ts"} <= set(tele)
    users = await database.db[Collections.USERS].index_information()
    assert users["email_unique"]["unique"] is True


async def test_seed_round_trip(repos: Repositories, bundle: SeedBundle):
    assert await repos.stops.count() == len(bundle.stops)
    r1 = await repos.routes.get("R1")
    assert r1.model_dump() == bundle.route("R1").model_dump()
    trip = (await repos.trips.on_date(SERVICE_DATE))[0]
    assert trip.scheduled_start.tzinfo is not None and trip.service_date == SERVICE_DATE


async def test_geo_near_and_serving_stop(repos: Repositories):
    s08 = await repos.stops.get("S08")
    hits = await repos.stops.near(s08.location, radius_m=3_000, limit=5)
    assert hits[0][0].id == "S08"
    assert [d for _, d in hits] == sorted(d for _, d in hits)
    assert [r.id for r in await repos.routes.serving_stop("S27")] == ["R3", "R4", "R6"]


async def test_trip_queries_and_status(repos: Repositories):
    trips = await repos.trips.for_bus_on("B03", SERVICE_DATE)
    assert [t.variant_id for t in trips] == ["R2", "R2-E"]
    t0 = datetime(2026, 10, 5, 1, 48, tzinfo=UTC)
    await repos.trips.set_status(trips[0].id, TripStatus.ACTIVE, t0)
    active = await repos.trips.active()
    assert [t.id for t in active] == [trips[0].id] and active[0].actual_start == t0


async def test_telemetry_round_trip(repos: Repositories):
    base = datetime(2026, 10, 5, 1, 45, tzinfo=UTC)
    items = [
        Telemetry(
            ts=base + timedelta(seconds=5 * i),
            meta=TelemetryMeta(bus_id="B01", trip_id="T-20261005-R1-0715", source=BusSource.SIM),
            location=GeoPoint.of(80.13 + i * 1e-4, 12.92),
            speed_mps=9.5,
            heading_deg=90.0,
            accuracy_m=8.0,
        )
        for i in range(3)
    ]
    await repos.telemetry.append_many(items)
    got = await repos.telemetry.recent("B01", since=base)
    assert [t.ts for t in got] == [t.ts for t in items]
    assert got[0].ts.tzinfo is not None
    assert len(await repos.telemetry.for_trip("T-20261005-R1-0715")) == 3


async def test_unique_email_enforced(repos: Repositories):
    dup = User(id="U-X", role=Role.STUDENT, name="Dup", email="student001@campusride.demo")
    with pytest.raises(ConflictError):
        await repos.users.upsert(dup)


async def test_reseed_is_idempotent(repos: Repositories, bundle: SeedBundle):
    await persist_seed(repos, bundle, SERVICE_DATE, DEFAULT_TZ)
    assert await repos.users.count() == len(bundle.users)
    assert await repos.trips.count() == 24


async def test_assignments_round_trip(repos: Repositories, bundle: SeedBundle):
    assert await repos.student_assignments.count() == len(bundle.student_assignments)
    a = await repos.student_assignments.get("U-S0001")
    assert a is not None and a.assigned_at.tzinfo is not None
    on_bus = await repos.student_assignments.for_bus(a.assigned_bus_id)
    assert "U-S0001" in {x.id for x in on_bus}
    assert await repos.student_assignments.get("U-S0025") is None


async def test_simulator_on_mongo(repos: Repositories):
    from datetime import datetime, timedelta

    from app.core.clock import ManualClock
    from app.core.config import Settings
    from app.core.events import InProcessEventBus
    from app.services.bus_simulator import BusSimulator
    from app.services.tracking import TelemetryIngestService

    start = datetime.combine(SERVICE_DATE, datetime.min.time(), tzinfo=DEFAULT_TZ) + timedelta(
        hours=7, minutes=15
    )
    clock = ManualClock(start)
    s = Settings(_env_file=None, app_env="test")
    sim = BusSimulator(repos, clock, TelemetryIngestService(repos, InProcessEventBus(), clock, s), s)
    await sim.reset()
    for _ in range(24):  # 2 simulated minutes
        clock.advance(5)
        await sim.step_until(clock.now())
    states = await repos.bus_states.list()
    assert len(states) == 12
    assert len(await repos.telemetry.recent("B01", since=start)) == 25
    await sim.reset()  # wipes synthetic telemetry/state and restarts
    assert len(await repos.telemetry.recent("B01", since=start)) == 1
    await sim.shutdown()


async def test_boarding_unique_student_trip_index(repos: Repositories):
    from app.models import BoardingEvent
    from app.models.common import BoardingSource, BoardingType

    def event(id_: str, student: str | None) -> BoardingEvent:
        return BoardingEvent(
            id=id_,
            trip_id="T-X",
            bus_id="B05",
            stop_id="S27",
            student_id=student,
            ts=datetime(2026, 10, 5, 2, 0, tzinfo=UTC),
            type=BoardingType.BOARD,
            source=BoardingSource.QR,
        )

    assert await repos.boarding_events.insert_once(event("BRD-1", "U-S0001")) is True
    assert await repos.boarding_events.insert_once(event("BRD-1", "U-S0001")) is False  # same id
    assert await repos.boarding_events.insert_once(event("BRD-2", "U-S0001")) is False  # same student+trip
    # anonymous (simulated) events are not constrained by the partial unique index
    assert await repos.boarding_events.insert_once(event("SIM-1", None)) is True
    assert await repos.boarding_events.insert_once(event("SIM-2", None)) is True
    assert await repos.boarding_events.count_for_trip("T-X") == 3
    assert (await repos.boarding_events.for_student_trip("U-S0001", "T-X")).id == "BRD-1"
    assert await repos.boarding_events.delete_for_buses(["B05"]) == 3
