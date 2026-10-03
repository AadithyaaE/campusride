"""Repository interfaces — the only way services touch persistence.

Services depend on these protocols, never on Motor. There are two
implementations of each:

* ``app.repositories.mongo``  — Motor / MongoDB (runtime)
* ``app.repositories.memory`` — dicts (unit & API tests; no database needed)

Filters are plain Mongo-style equality dicts (dotted paths allowed, plus
``$in``), which both implementations understand.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol, TypeVar

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
from app.models.common import Document, TripStatus

T = TypeVar("T", bound=Document)
Filter = Mapping[str, Any]

DEFAULT_LIMIT = 1_000


class Repository(Protocol[T]):
    async def get(self, id: str) -> T | None: ...

    async def get_many(self, ids: Sequence[str]) -> list[T]:
        """Documents for ``ids`` (missing ids are skipped), ordered by id."""
        ...

    async def list(self, *, filter: Filter | None = None, limit: int = DEFAULT_LIMIT) -> list[T]:
        """Matching documents ordered by id."""
        ...

    async def count(self, *, filter: Filter | None = None) -> int: ...

    async def upsert(self, item: T) -> T: ...

    async def insert_many(self, items: Sequence[T]) -> None: ...

    async def delete(self, id: str) -> bool: ...

    async def delete_all(self) -> int: ...


class CampusRepository(Repository[Campus], Protocol): ...


class StopRepository(Repository[Stop], Protocol):
    async def near(self, point: GeoPoint, radius_m: float, limit: int = 10) -> list[tuple[Stop, float]]:
        """Stops within ``radius_m``, nearest first, with their distance in metres."""
        ...


class RouteRepository(Repository[Route], Protocol):
    async def serving_stop(self, stop_id: str) -> list[Route]:
        """Routes with the stop in either direction."""
        ...


class BusRepository(Repository[Bus], Protocol): ...


class DriverRepository(Repository[Driver], Protocol):
    async def by_user(self, user_id: str) -> Driver | None: ...


class TripRepository(Repository[Trip], Protocol):
    async def active(self, *, route_id: str | None = None) -> list[Trip]: ...

    async def for_bus_on(self, bus_id: str, service_date: date) -> list[Trip]:
        """A bus's trips on a service date, by scheduled start."""
        ...

    async def on_date(self, service_date: date) -> list[Trip]: ...

    async def set_status(self, trip_id: str, status: TripStatus, at: datetime) -> Trip | None:
        """Change status; ACTIVE stamps ``actual_start``, COMPLETED/CANCELLED stamp ``actual_end``."""
        ...


class TelemetryRepository(Protocol):
    """Append-only time series; no update or delete."""

    async def append_many(self, items: Sequence[Telemetry]) -> None: ...

    async def recent(self, bus_id: str, since: datetime, limit: int = 500) -> list[Telemetry]:
        """Readings for a bus at or after ``since``, oldest first."""
        ...

    async def for_trip(self, trip_id: str, limit: int = 10_000) -> list[Telemetry]: ...

    async def delete_for_buses(self, bus_ids: Sequence[str]) -> int: ...

    async def delete_all(self) -> int: ...


class BusStateRepository(Repository[BusState], Protocol):
    async def by_route(self, route_id: str) -> list[BusState]: ...

    async def by_variants(self, variant_ids: Sequence[str]) -> list[BusState]:
        """States of buses currently operating any of these route directions."""
        ...


class UserRepository(Repository[User], Protocol):
    async def by_email(self, email: str) -> User | None: ...


class StudentProfileRepository(Repository[StudentProfile], Protocol):
    async def by_home_stop(self, stop_id: str) -> list[StudentProfile]: ...


class StudentAssignmentRepository(Repository[StudentAssignment], Protocol):
    """College-assigned transport; ``id`` = student user id."""

    async def for_bus(self, bus_id: str) -> list[StudentAssignment]: ...


class BoardingEventRepository(Repository[BoardingEvent], Protocol):
    async def for_trip(self, trip_id: str) -> list[BoardingEvent]: ...

    async def insert_once(self, event: BoardingEvent) -> bool:
        """Insert unless this (student_id, trip_id) — or this id — already exists. Atomic.
        Returns False for a duplicate (nothing written)."""
        ...

    async def for_student_trip(self, student_id: str, trip_id: str) -> BoardingEvent | None: ...

    async def count_for_trip(self, trip_id: str) -> int: ...

    async def delete_for_buses(self, bus_ids: Sequence[str]) -> int: ...


class DeviationRepository(Repository[Deviation], Protocol):
    async def open_for_bus(self, bus_id: str) -> Deviation | None: ...


class AlertRepository(Repository[Alert], Protocol):
    async def recent(self, limit: int = 100) -> list[Alert]:
        """Newest first."""
        ...


class TrafficProfileRepository(Repository[TrafficProfile], Protocol): ...


@dataclass(frozen=True)
class Repositories:
    """All repositories, injected as one unit (see ``app.deps``)."""

    campuses: CampusRepository
    stops: StopRepository
    routes: RouteRepository
    buses: BusRepository
    drivers: DriverRepository
    trips: TripRepository
    telemetry: TelemetryRepository
    bus_states: BusStateRepository
    users: UserRepository
    student_profiles: StudentProfileRepository
    student_assignments: StudentAssignmentRepository
    boarding_events: BoardingEventRepository
    deviations: DeviationRepository
    alerts: AlertRepository
    traffic_profiles: TrafficProfileRepository
