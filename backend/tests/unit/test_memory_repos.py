"""In-memory repositories must behave like the Mongo ones (also covered by integration tests)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ConflictError
from app.models import GeoPoint, Telemetry, TelemetryMeta
from app.models.common import BusSource, TripStatus
from app.repositories.base import Repositories
from app.repositories.filters import matches
from tests.conftest import SERVICE_DATE


def test_filter_semantics():
    doc = {"a": 1, "nested": {"b": "x"}, "items": [{"id": "S1"}, {"id": "S2"}], "tags": ["t1", "t2"]}
    assert matches(doc, {"a": 1})
    assert matches(doc, {"nested.b": "x"})
    assert matches(doc, {"items.id": "S2"})  # dotted path through an array
    assert matches(doc, {"tags": "t2"})  # array contains
    assert matches(doc, {"a": {"$in": [0, 1]}})
    assert not matches(doc, {"items.id": "S3"})
    assert not matches(doc, {"missing": 1})
    with pytest.raises(NotImplementedError):
        matches(doc, {"a": {"$gt": 0}})


async def test_seeded_reference_data(container):
    repos: Repositories = container.repos
    assert await repos.stops.count() == 39
    assert await repos.routes.count() == 6
    assert await repos.trips.count() == 24
    serving = await repos.routes.serving_stop("S08")
    assert [r.id for r in serving] == ["R1", "R2", "R5"]


async def test_near_orders_by_distance(container):
    s08 = await container.repos.stops.get("S08")
    hits = await container.repos.stops.near(s08.location, radius_m=3_000, limit=5)
    assert hits[0][0].id == "S08" and hits[0][1] == pytest.approx(0, abs=0.01)
    assert [d for _, d in hits] == sorted(d for _, d in hits)
    assert all(d <= 3_000 for _, d in hits)


async def test_insert_duplicate_conflicts(container):
    stop = await container.repos.stops.get("S01")
    with pytest.raises(ConflictError):
        await container.repos.stops.insert_many([stop])


async def test_trip_status_transitions(container):
    repos = container.repos
    trips = await repos.trips.for_bus_on("B01", SERVICE_DATE)
    assert [t.direction.value for t in trips] == ["to_campus", "from_campus"]
    t0 = datetime(2026, 10, 5, 1, 45, tzinfo=UTC)
    started = await repos.trips.set_status(trips[0].id, TripStatus.ACTIVE, t0)
    assert started.actual_start == t0
    assert [t.id for t in await repos.trips.active(route_id="R1")] == [trips[0].id]
    done = await repos.trips.set_status(trips[0].id, TripStatus.COMPLETED, t0 + timedelta(minutes=35))
    assert done.actual_start == t0 and done.actual_end == t0 + timedelta(minutes=35)
    assert await repos.trips.set_status("nope", TripStatus.ACTIVE, t0) is None


async def test_telemetry_append_and_query(container):
    base = datetime(2026, 10, 5, 1, 45, tzinfo=UTC)
    readings = [
        Telemetry(
            ts=base + timedelta(seconds=5 * i),
            meta=TelemetryMeta(bus_id="B01", trip_id="T1", source=BusSource.SIM),
            location=GeoPoint.of(80.13, 12.92),
            speed_mps=8.0,
            accuracy_m=8.0,
        )
        for i in range(4)
    ]
    await container.repos.telemetry.append_many(list(reversed(readings)))
    recent = await container.repos.telemetry.recent("B01", since=base + timedelta(seconds=5))
    assert [r.ts for r in recent] == [r.ts for r in readings[1:]]
    assert len(await container.repos.telemetry.for_trip("T1")) == 4
