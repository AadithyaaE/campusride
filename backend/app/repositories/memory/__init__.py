"""In-memory repositories (tests and offline tooling). Same behaviour as the Mongo ones."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Generic, TypeVar

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
from app.repositories.filters import date_key, matches, trip_with_status

T = TypeVar("T", bound=Document)


class MemoryRepository(Generic[T]):
    def __init__(self, model: type[T]) -> None:
        self._model = model
        self._docs: dict[str, dict[str, Any]] = {}

    def _load(self, raw: dict[str, Any]) -> T:
        return self._model.from_mongo(copy.deepcopy(raw))

    async def get(self, id: str) -> T | None:
        raw = self._docs.get(id)
        return None if raw is None else self._load(raw)

    async def get_many(self, ids: Sequence[str]) -> list[T]:
        return [self._load(self._docs[i]) for i in sorted(set(ids)) if i in self._docs]

    async def list(self, *, filter: Filter | None = None, limit: int = DEFAULT_LIMIT) -> list[T]:
        out = [self._load(self._docs[k]) for k in sorted(self._docs) if matches(self._docs[k], filter)]
        return out[:limit]

    async def count(self, *, filter: Filter | None = None) -> int:
        return sum(1 for d in self._docs.values() if matches(d, filter))

    async def upsert(self, item: T) -> T:
        self._docs[item.id] = item.to_mongo()
        return item

    async def insert_many(self, items: Sequence[T]) -> None:
        ids = [i.id for i in items]
        dupes = (set(ids) & set(self._docs)) | {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ConflictError(f"duplicate ids: {sorted(dupes)[:5]}")
        for item in items:
            self._docs[item.id] = item.to_mongo()

    async def delete(self, id: str) -> bool:
        return self._docs.pop(id, None) is not None

    async def delete_all(self) -> int:
        n = len(self._docs)
        self._docs.clear()
        return n


class MemoryStopRepository(MemoryRepository[Stop]):
    async def near(self, point: GeoPoint, radius_m: float, limit: int = 10) -> list[tuple[Stop, float]]:
        hits = []
        for stop in await self.list():
            d = haversine_m(point.lnglat, stop.location.lnglat)
            if d <= radius_m:
                hits.append((stop, d))
        hits.sort(key=lambda h: (h[1], h[0].id))
        return hits[:limit]


class MemoryRouteRepository(MemoryRepository[Route]):
    async def serving_stop(self, stop_id: str) -> list[Route]:
        return await self.list(filter={"directions.stops.stop_id": stop_id})


class MemoryDriverRepository(MemoryRepository[Driver]):
    async def by_user(self, user_id: str) -> Driver | None:
        found = await self.list(filter={"user_id": user_id}, limit=1)
        return found[0] if found else None


class MemoryTripRepository(MemoryRepository[Trip]):
    async def active(self, *, route_id: str | None = None) -> list[Trip]:
        flt: dict[str, Any] = {"status": TripStatus.ACTIVE.value}
        if route_id:
            flt["route_id"] = route_id
        return await self.list(filter=flt)

    async def for_bus_on(self, bus_id: str, service_date: date) -> list[Trip]:
        trips = await self.list(filter={"bus_id": bus_id, "service_date": date_key(service_date)})
        return sorted(trips, key=lambda t: t.scheduled_start)

    async def on_date(self, service_date: date) -> list[Trip]:
        return await self.list(filter={"service_date": date_key(service_date)})

    async def set_status(self, trip_id: str, status: TripStatus, at: datetime) -> Trip | None:
        trip = await self.get(trip_id)
        if trip is None:
            return None
        return await self.upsert(trip_with_status(trip, status, at))


class MemoryTelemetryRepository:
    def __init__(self) -> None:
        self._items: list[Telemetry] = []

    async def append_many(self, items: Sequence[Telemetry]) -> None:
        self._items.extend(t.model_copy(deep=True) for t in items)

    async def recent(self, bus_id: str, since: datetime, limit: int = 500) -> list[Telemetry]:
        hits = [t for t in self._items if t.meta.bus_id == bus_id and t.ts >= since]
        return sorted(hits, key=lambda t: t.ts)[:limit]

    async def for_trip(self, trip_id: str, limit: int = 10_000) -> list[Telemetry]:
        hits = [t for t in self._items if t.meta.trip_id == trip_id]
        return sorted(hits, key=lambda t: t.ts)[:limit]

    async def delete_for_buses(self, bus_ids: Sequence[str]) -> int:
        keep = [t for t in self._items if t.meta.bus_id not in set(bus_ids)]
        n = len(self._items) - len(keep)
        self._items = keep
        return n

    async def delete_all(self) -> int:
        n = len(self._items)
        self._items.clear()
        return n


class MemoryBusStateRepository(MemoryRepository[BusState]):
    async def by_route(self, route_id: str) -> list[BusState]:
        return await self.list(filter={"route_id": route_id})

    async def by_variants(self, variant_ids: Sequence[str]) -> list[BusState]:
        return await self.list(filter={"variant_id": {"$in": list(variant_ids)}})


class MemoryUserRepository(MemoryRepository[User]):
    async def by_email(self, email: str) -> User | None:
        found = await self.list(filter={"email": email.strip().lower()}, limit=1)
        return found[0] if found else None

    async def by_auth_subject(self, provider: str, subject: str) -> User | None:
        found = await self.list(filter={"auth_provider": provider, "auth_subject": subject}, limit=1)
        return found[0] if found else None


class MemoryStudentProfileRepository(MemoryRepository[StudentProfile]):
    async def by_home_stop(self, stop_id: str) -> list[StudentProfile]:
        return await self.list(filter={"home_stop_id": stop_id})


class MemoryStudentAssignmentRepository(MemoryRepository[StudentAssignment]):
    async def for_bus(self, bus_id: str) -> list[StudentAssignment]:
        return await self.list(filter={"assigned_bus_id": bus_id}, limit=100_000)


class MemoryBoardingEventRepository(MemoryRepository[BoardingEvent]):
    async def for_trip(self, trip_id: str) -> list[BoardingEvent]:
        events = await self.list(filter={"trip_id": trip_id}, limit=100_000)
        return sorted(events, key=lambda e: e.ts)

    async def insert_once(self, event: BoardingEvent) -> bool:
        # No await between the check and the write → atomic on the event loop
        # (mirrors the unique (student_id, trip_id) index in MongoDB).
        if event.id in self._docs:
            return False
        if event.student_id is not None and any(
            d.get("student_id") == event.student_id and d.get("trip_id") == event.trip_id
            for d in self._docs.values()
        ):
            return False
        self._docs[event.id] = event.to_mongo()
        return True

    async def for_student_trip(self, student_id: str, trip_id: str) -> BoardingEvent | None:
        found = await self.list(filter={"student_id": student_id, "trip_id": trip_id}, limit=1)
        return found[0] if found else None

    async def count_for_trip(self, trip_id: str) -> int:
        return await self.count(filter={"trip_id": trip_id, "type": "board"})

    async def delete_for_buses(self, bus_ids: Sequence[str]) -> int:
        doomed = [k for k, d in self._docs.items() if d.get("bus_id") in set(bus_ids)]
        for k in doomed:
            del self._docs[k]
        return len(doomed)

    async def delete_for_trips(self, trip_ids: Sequence[str]) -> int:
        doomed = [k for k, d in self._docs.items() if d.get("trip_id") in set(trip_ids)]
        for k in doomed:
            del self._docs[k]
        return len(doomed)


class MemoryDeviationRepository(MemoryRepository[Deviation]):
    async def open_for_bus(self, bus_id: str) -> Deviation | None:
        found = await self.list(filter={"bus_id": bus_id, "status": DeviationStatus.OPEN.value})
        return max(found, key=lambda d: d.started_at) if found else None


class MemoryAlertRepository(MemoryRepository[Alert]):
    async def recent(self, limit: int = 100) -> list[Alert]:
        alerts = await self.list(limit=100_000)
        return sorted(alerts, key=lambda a: (a.created_at, a.id), reverse=True)[:limit]

    async def insert_once(self, alert: Alert) -> bool:
        # check-and-set without an await → atomic on the event loop (mirrors Mongo's indexes)
        if alert.id in self._docs:
            return False
        if (
            alert.active
            and alert.dedup_key is not None
            and any(d.get("dedup_key") == alert.dedup_key and d.get("active") for d in self._docs.values())
        ):
            return False
        self._docs[alert.id] = alert.to_mongo()
        return True

    async def active_in_series(self, dedup_key: str) -> Alert | None:
        found = await self.list(filter={"dedup_key": dedup_key, "active": True}, limit=1)
        return found[0] if found else None

    async def count_series(self, dedup_key: str) -> int:
        return await self.count(filter={"dedup_key": dedup_key})

    async def active_for_bus(self, bus_id: str, types: Sequence[str]) -> list[Alert]:
        found = await self.list(filter={"bus_id": bus_id, "active": True}, limit=100_000)
        return [a for a in found if a.type.value in set(types)]

    async def active_keys(self, prefix_types: Sequence[str]) -> set[str]:
        return {
            d["dedup_key"]
            for d in self._docs.values()
            if d.get("active") and d.get("dedup_key") and d.get("type") in set(prefix_types)
        }

    async def series_keys(self, prefix_types: Sequence[str]) -> set[str]:
        return {
            d["dedup_key"]
            for d in self._docs.values()
            if d.get("dedup_key") and d.get("type") in set(prefix_types)
        }

    async def for_recipient(
        self,
        *,
        user_id: str | None = None,
        role: str | None = None,
        active: bool | None = None,
        unread: bool | None = None,
        limit: int = 50,
    ) -> list[Alert]:
        out = []
        for d in self._docs.values():
            aud = d.get("audience") or {}
            if user_id is not None and aud.get("user_id") != user_id:
                continue
            if role is not None and aud.get("role") != role:
                continue
            if active is not None and bool(d.get("active")) != active:
                continue
            if unread is not None and (not d.get("read")) != unread:
                continue
            out.append(self._load(d))
        return sorted(out, key=lambda a: (a.created_at, a.id), reverse=True)[:limit]

    async def delete_for_buses(self, bus_ids: Sequence[str]) -> int:
        doomed = [k for k, d in self._docs.items() if d.get("bus_id") in set(bus_ids)]
        for k in doomed:
            del self._docs[k]
        return len(doomed)

    async def delete_for_trips(self, bus_ids: Sequence[str], trip_ids: Sequence[str]) -> int:
        buses, trips = set(bus_ids), set(trip_ids)
        doomed = [
            k
            for k, d in self._docs.items()
            if d.get("bus_id") in buses and (d.get("trip_id") is None or d.get("trip_id") in trips)
        ]
        for k in doomed:
            del self._docs[k]
        return len(doomed)

    async def resolve_active_for_buses(self, bus_ids: Sequence[str], ts: datetime) -> int:
        hits = [a for a in await self.list(filter={"bus_id": {"$in": list(bus_ids)}, "active": True})]
        for a in hits:
            await self.upsert(a.model_copy(update={"active": False, "resolved_at": ts}))
        return len(hits)


def memory_repositories() -> Repositories:
    return Repositories(
        campuses=MemoryRepository(Campus),
        stops=MemoryStopRepository(Stop),
        routes=MemoryRouteRepository(Route),
        buses=MemoryRepository(Bus),
        drivers=MemoryDriverRepository(Driver),
        trips=MemoryTripRepository(Trip),
        telemetry=MemoryTelemetryRepository(),
        bus_states=MemoryBusStateRepository(BusState),
        users=MemoryUserRepository(User),
        student_profiles=MemoryStudentProfileRepository(StudentProfile),
        student_assignments=MemoryStudentAssignmentRepository(StudentAssignment),
        boarding_events=MemoryBoardingEventRepository(BoardingEvent),
        deviations=MemoryDeviationRepository(Deviation),
        alerts=MemoryAlertRepository(Alert),
        traffic_profiles=MemoryRepository(TrafficProfile),
    )
