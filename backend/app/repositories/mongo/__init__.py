"""MongoDB (Motor) repositories."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Generic, TypeVar

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import BulkWriteError, DuplicateKeyError

from app.core.db import Collections
from app.core.errors import ConflictError
from app.geo import haversine_m
from app.models import (
    Alert,
    BoardingEvent,
    Bus,
    BusState,
    Campus,
    Deviation,
    Driver,
    GeoPoint,
    Route,
    Stop,
    StudentAssignment,
    StudentProfile,
    Telemetry,
    TrafficProfile,
    Trip,
    User,
)
from app.models.common import DeviationStatus, Document, TripStatus
from app.repositories.base import DEFAULT_LIMIT, Filter, Repositories
from app.repositories.filters import date_key, trip_with_status

T = TypeVar("T", bound=Document)
DUPLICATE_KEY = 11000


class MongoRepository(Generic[T]):
    def __init__(self, coll: AsyncIOMotorCollection, model: type[T]) -> None:
        self._coll = coll
        self._model = model

    async def get(self, id: str) -> T | None:
        raw = await self._coll.find_one({"_id": id})
        return None if raw is None else self._model.from_mongo(raw)

    async def get_many(self, ids: Sequence[str]) -> list[T]:
        cursor = self._coll.find({"_id": {"$in": list(set(ids))}}).sort("_id", ASCENDING)
        return [self._model.from_mongo(r) async for r in cursor]

    async def list(self, *, filter: Filter | None = None, limit: int = DEFAULT_LIMIT) -> list[T]:
        cursor = self._coll.find(dict(filter or {})).sort("_id", ASCENDING).limit(limit)
        return [self._model.from_mongo(r) async for r in cursor]

    async def _find_sorted(self, flt: Filter, sort: list[tuple[str, int]], limit: int = 0) -> list[T]:
        cursor = self._coll.find(dict(flt)).sort(sort).limit(limit)
        return [self._model.from_mongo(r) async for r in cursor]

    async def count(self, *, filter: Filter | None = None) -> int:
        return await self._coll.count_documents(dict(filter or {}))

    async def upsert(self, item: T) -> T:
        try:
            await self._coll.replace_one({"_id": item.id}, item.to_mongo(), upsert=True)
        except DuplicateKeyError as exc:  # a unique secondary index (e.g. email)
            raise ConflictError(str(exc.details or exc)) from exc
        return item

    async def insert_many(self, items: Sequence[T]) -> None:
        if not items:
            return
        try:
            await self._coll.insert_many([i.to_mongo() for i in items], ordered=True)
        except BulkWriteError as exc:
            if any(e.get("code") == DUPLICATE_KEY for e in exc.details.get("writeErrors", [])):
                raise ConflictError("duplicate key on insert") from exc
            raise

    async def delete(self, id: str) -> bool:
        res = await self._coll.delete_one({"_id": id})
        return res.deleted_count == 1

    async def delete_all(self) -> int:
        res = await self._coll.delete_many({})
        return res.deleted_count


class MongoStopRepository(MongoRepository[Stop]):
    async def near(self, point: GeoPoint, radius_m: float, limit: int = 10) -> list[tuple[Stop, float]]:
        query = {"location": {"$nearSphere": {"$geometry": point.model_dump(), "$maxDistance": radius_m}}}
        cursor = self._coll.find(query).limit(limit)
        stops = [Stop.from_mongo(r) async for r in cursor]
        hits = [(s, haversine_m(point.lnglat, s.location.lnglat)) for s in stops]
        hits.sort(key=lambda h: (h[1], h[0].id))
        return hits


class MongoRouteRepository(MongoRepository[Route]):
    async def serving_stop(self, stop_id: str) -> list[Route]:
        return await self.list(filter={"directions.stops.stop_id": stop_id})


class MongoDriverRepository(MongoRepository[Driver]):
    async def by_user(self, user_id: str) -> Driver | None:
        raw = await self._coll.find_one({"user_id": user_id})
        return None if raw is None else Driver.from_mongo(raw)


class MongoTripRepository(MongoRepository[Trip]):
    async def active(self, *, route_id: str | None = None) -> list[Trip]:
        flt: dict[str, Any] = {"status": TripStatus.ACTIVE.value}
        if route_id:
            flt["route_id"] = route_id
        return await self.list(filter=flt)

    async def for_bus_on(self, bus_id: str, service_date: date) -> list[Trip]:
        return await self._find_sorted(
            {"bus_id": bus_id, "service_date": date_key(service_date)}, [("scheduled_start", ASCENDING)]
        )

    async def on_date(self, service_date: date) -> list[Trip]:
        return await self.list(filter={"service_date": date_key(service_date)})

    async def set_status(self, trip_id: str, status: TripStatus, at: datetime) -> Trip | None:
        trip = await self.get(trip_id)
        if trip is None:
            return None
        return await self.upsert(trip_with_status(trip, status, at))


class MongoTelemetryRepository:
    def __init__(self, coll: AsyncIOMotorCollection) -> None:
        self._coll = coll

    async def append_many(self, items: Sequence[Telemetry]) -> None:
        if items:
            await self._coll.insert_many([t.model_dump(mode="python") for t in items], ordered=False)

    async def _find(self, flt: dict[str, Any], limit: int) -> list[Telemetry]:
        cursor = self._coll.find(flt).sort("ts", ASCENDING).limit(limit)
        return [Telemetry.model_validate(r) async for r in cursor]

    async def recent(self, bus_id: str, since: datetime, limit: int = 500) -> list[Telemetry]:
        return await self._find({"meta.bus_id": bus_id, "ts": {"$gte": since}}, limit)

    async def for_trip(self, trip_id: str, limit: int = 10_000) -> list[Telemetry]:
        return await self._find({"meta.trip_id": trip_id}, limit)

    async def delete_for_buses(self, bus_ids: Sequence[str]) -> int:
        res = await self._coll.delete_many({"meta.bus_id": {"$in": list(bus_ids)}})
        return res.deleted_count

    async def delete_all(self) -> int:
        res = await self._coll.delete_many({})
        return res.deleted_count


class MongoBusStateRepository(MongoRepository[BusState]):
    async def by_route(self, route_id: str) -> list[BusState]:
        return await self.list(filter={"route_id": route_id})

    async def by_variants(self, variant_ids: Sequence[str]) -> list[BusState]:
        return await self.list(filter={"variant_id": {"$in": list(variant_ids)}})


class MongoUserRepository(MongoRepository[User]):
    async def by_email(self, email: str) -> User | None:
        raw = await self._coll.find_one({"email": email.strip().lower()})
        return None if raw is None else User.from_mongo(raw)


class MongoStudentProfileRepository(MongoRepository[StudentProfile]):
    async def by_home_stop(self, stop_id: str) -> list[StudentProfile]:
        return await self.list(filter={"home_stop_id": stop_id})


class MongoStudentAssignmentRepository(MongoRepository[StudentAssignment]):
    async def for_bus(self, bus_id: str) -> list[StudentAssignment]:
        return await self.list(filter={"assigned_bus_id": bus_id}, limit=100_000)


class MongoBoardingEventRepository(MongoRepository[BoardingEvent]):
    async def for_trip(self, trip_id: str) -> list[BoardingEvent]:
        return await self._find_sorted({"trip_id": trip_id}, [("ts", ASCENDING)])


class MongoDeviationRepository(MongoRepository[Deviation]):
    async def open_for_bus(self, bus_id: str) -> Deviation | None:
        found = await self._find_sorted(
            {"bus_id": bus_id, "status": DeviationStatus.OPEN.value}, [("started_at", DESCENDING)], limit=1
        )
        return found[0] if found else None


class MongoAlertRepository(MongoRepository[Alert]):
    async def recent(self, limit: int = 100) -> list[Alert]:
        return await self._find_sorted({}, [("created_at", DESCENDING)], limit=limit)


def mongo_repositories(db: AsyncIOMotorDatabase) -> Repositories:
    c = Collections
    return Repositories(
        campuses=MongoRepository(db[c.CAMPUSES], Campus),
        stops=MongoStopRepository(db[c.STOPS], Stop),
        routes=MongoRouteRepository(db[c.ROUTES], Route),
        buses=MongoRepository(db[c.BUSES], Bus),
        drivers=MongoDriverRepository(db[c.DRIVERS], Driver),
        trips=MongoTripRepository(db[c.TRIPS], Trip),
        telemetry=MongoTelemetryRepository(db[c.TELEMETRY]),
        bus_states=MongoBusStateRepository(db[c.BUS_STATES], BusState),
        users=MongoUserRepository(db[c.USERS], User),
        student_profiles=MongoStudentProfileRepository(db[c.STUDENT_PROFILES], StudentProfile),
        student_assignments=MongoStudentAssignmentRepository(db[c.STUDENT_ASSIGNMENTS], StudentAssignment),
        boarding_events=MongoBoardingEventRepository(db[c.BOARDING_EVENTS], BoardingEvent),
        deviations=MongoDeviationRepository(db[c.DEVIATIONS], Deviation),
        alerts=MongoAlertRepository(db[c.ALERTS], Alert),
        traffic_profiles=MongoRepository(db[c.TRAFFIC_PROFILES], TrafficProfile),
    )
