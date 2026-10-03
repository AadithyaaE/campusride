"""Student transport assignments (college/admin-assigned bus).

Students never choose their bus, route or stop. An assignment is created by
the college (admin API/UI later; deterministic seed data for now) and is
read-only for the student.

``validate_assignment`` holds the integrity rules and is shared by every
writer (seeding today, admin endpoints later):

* the student exists and is a student,
* the bus exists and is in active service,
* the route direction (variant) exists,
* the bus belongs to that route (``Bus.default_route_id``),
* the boarding stop is served by that direction and is not its final stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.errors import ConflictError, NotFoundError
from app.models import Bus, Route, RouteDirection, RouteStop, Stop, User
from app.models.assignment import StudentAssignment
from app.models.common import FleetStatus, Role
from app.repositories import Repositories


@dataclass(frozen=True)
class ResolvedAssignment:
    """An assignment joined with the reference data it points at."""

    assignment: StudentAssignment
    bus: Bus
    route: Route
    direction: RouteDirection
    boarding_stop: Stop
    route_stop: RouteStop


def find_variant(routes: list[Route], variant_id: str) -> tuple[Route, RouteDirection] | None:
    for route in routes:
        for direction in route.directions:
            if direction.variant_id == variant_id:
                return route, direction
    return None


def validate_assignment(
    a: StudentAssignment,
    *,
    student: User | None,
    bus: Bus | None,
    routes: list[Route],
) -> list[str]:
    """Integrity problems with an assignment (empty list = valid)."""
    problems: list[str] = []
    if student is None:
        problems.append(f"student {a.id} does not exist")
    elif student.role is not Role.STUDENT:
        problems.append(f"user {a.id} is not a student")
    if bus is None:
        problems.append(f"bus {a.assigned_bus_id} does not exist")
    elif bus.status is not FleetStatus.ACTIVE:
        problems.append(f"bus {bus.id} is not in active service ({bus.status.value})")

    found = find_variant(routes, a.assigned_route_direction_id)
    if found is None:
        problems.append(f"route direction {a.assigned_route_direction_id} does not exist")
        return problems
    route, direction = found
    if bus is not None and bus.default_route_id != route.id:
        problems.append(
            f"bus {bus.id} runs route {bus.default_route_id}, not {route.id} ({direction.variant_id})"
        )
    rs = direction.stop(a.boarding_stop_id)
    if rs is None:
        problems.append(f"stop {a.boarding_stop_id} is not served by {direction.variant_id}")
    elif rs.seq == len(direction.stops) - 1:
        problems.append(
            f"stop {a.boarding_stop_id} is the final stop of {direction.variant_id}; nobody boards there"
        )
    return problems


class AssignmentService:
    def __init__(self, repos: Repositories) -> None:
        self._repos = repos

    async def validate(self, a: StudentAssignment) -> list[str]:
        return validate_assignment(
            a,
            student=await self._repos.users.get(a.id),
            bus=await self._repos.buses.get(a.assigned_bus_id),
            routes=await self._repos.routes.list(),
        )

    async def assign(self, a: StudentAssignment) -> StudentAssignment:
        """Create or replace an assignment (college/admin side only)."""
        problems = await self.validate(a)
        if problems:
            raise ConflictError("; ".join(problems))
        return await self._repos.student_assignments.upsert(a)

    async def for_student(self, student_id: str) -> ResolvedAssignment | None:
        """The student's assignment joined with bus/route/stop, or None if unassigned."""
        a = await self._repos.student_assignments.get(student_id)
        if a is None:
            return None
        bus = await self._repos.buses.get(a.assigned_bus_id)
        routes = await self._repos.routes.list()
        found = find_variant(routes, a.assigned_route_direction_id)
        stop = await self._repos.stops.get(a.boarding_stop_id)
        rs = found[1].stop(a.boarding_stop_id) if found else None
        if bus is None or found is None or stop is None or rs is None:
            # Reference data changed underneath a stored assignment.
            raise NotFoundError(f"assignment for {student_id} references data that no longer exists")
        return ResolvedAssignment(
            assignment=a, bus=bus, route=found[0], direction=found[1], boarding_stop=stop, route_stop=rs
        )


def new_assignment(
    student_id: str, bus_id: str, variant_id: str, stop_id: str, *, by: str, at: datetime
) -> StudentAssignment:
    return StudentAssignment(
        id=student_id,
        assigned_bus_id=bus_id,
        assigned_route_direction_id=variant_id,
        boarding_stop_id=stop_id,
        assigned_by=by,
        assigned_at=at,
    )
