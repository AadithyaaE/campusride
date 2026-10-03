"""Student self-service — read-only. Transport assignments are set by the college/admin."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import Principal
from app.core.errors import ForbiddenError, NotFoundError
from app.deps import Container, CurrentPrincipal, Repos, require_role
from app.models.api.comparison import BusOptionOut, BusOptionsOut, ExcludedBusOut
from app.models.api.eta import ArrivalOut, EtaPredictionOut, MyArrivalsOut
from app.models.api.matching import MyStopBusesOut, StopBusOut, StopSummaryOut
from app.models.api.students import AssignmentOut, MyAssignmentOut
from app.models.common import Role
from app.services.assignments import AssignmentService
from app.services.bus_comparison_service import BusOption, StudentBusOptions

router = APIRouter(tags=["students"])

Student = Annotated[Principal, Depends(require_role(Role.STUDENT))]


@router.get("/students/me/assignment", response_model=MyAssignmentOut)
async def my_assignment(principal: Student, repos: Repos) -> MyAssignmentOut:
    """The signed-in student's college-assigned bus, route direction and boarding stop."""
    resolved = await AssignmentService(repos).for_student(principal.user_id)
    if resolved is None:
        return MyAssignmentOut(student_id=principal.user_id, status="unassigned", assignment=None)
    return MyAssignmentOut(
        student_id=principal.user_id, status="assigned", assignment=AssignmentOut.of(resolved)
    )


@router.get("/students/me/stop/buses", response_model=MyStopBusesOut)
async def my_stop_buses(principal: Student, c: Container) -> MyStopBusesOut:
    """The student's assigned bus and other buses serving their boarding stop (read-only)."""
    result = await c.matching().for_student(principal.user_id)
    if result is None:
        return MyStopBusesOut(
            student_id=principal.user_id,
            status="unassigned",
            boarding_stop=None,
            assigned_bus_id=None,
            route_direction_id=None,
            direction=None,
            my_bus=None,
            my_bus_serving_stop=False,
            other_buses=[],
        )
    a = result.assignment
    involved = [*result.others, *([result.my_bus] if result.my_bus else [])]
    names = await c.matching().stop_names(involved)
    stale_after = c.settings.bus_stale_after_s

    def out(sb):
        return StopBusOut.of(sb, names, c.clock, stale_after, assigned_bus_id=a.bus.id)

    return MyStopBusesOut(
        student_id=principal.user_id,
        status="assigned",
        boarding_stop=StopSummaryOut(id=a.boarding_stop.id, name=a.boarding_stop.name),
        assigned_bus_id=a.bus.id,
        route_direction_id=a.direction.variant_id,
        direction=a.direction.direction,
        my_bus=out(result.my_bus) if result.my_bus else None,
        my_bus_serving_stop=bool(result.my_bus and result.my_bus.match),
        other_buses=[out(sb) for sb in result.others],
    )


@router.get("/students/me/arrivals", response_model=MyArrivalsOut)
async def my_arrivals(principal: Student, c: Container) -> MyArrivalsOut:
    """Backend ETAs for every bus serving the student's ASSIGNED boarding stop and direction."""
    result = await c.eta().student_arrivals(principal.user_id)
    if result is None:
        return MyArrivalsOut(
            student_id=principal.user_id,
            status="unassigned",
            boarding_stop=None,
            assigned_bus_id=None,
            route_direction_id=None,
            direction=None,
            my_bus=None,
            my_bus_serving_stop=False,
            arrivals=[],
        )
    a = result.assignment
    involved = [sb for sb, _ in result.arrivals] + ([result.my_bus[0]] if result.my_bus else [])
    names = await c.matching().stop_names(involved)
    stale_after = c.settings.bus_stale_after_s

    def arrival(sb, p) -> ArrivalOut:
        base = StopBusOut.of(sb, names, c.clock, stale_after, assigned_bus_id=a.bus.id)
        return ArrivalOut(**base.model_dump(), eta=EtaPredictionOut.of(p))

    my_bus = None
    if result.my_bus is not None:
        sb, p = result.my_bus
        my_bus = (
            arrival(sb, p)
            if p is not None
            else StopBusOut.of(sb, names, c.clock, stale_after, assigned_bus_id=a.bus.id)
        )
    return MyArrivalsOut(
        student_id=principal.user_id,
        status="assigned",
        boarding_stop=StopSummaryOut(id=a.boarding_stop.id, name=a.boarding_stop.name),
        assigned_bus_id=a.bus.id,
        route_direction_id=a.direction.variant_id,
        direction=a.direction.direction,
        my_bus=my_bus,
        my_bus_serving_stop=result.my_bus is not None and result.my_bus[1] is not None,
        arrivals=[arrival(sb, p) for sb, p in result.arrivals],
    )


# --------------------------------------------------------------------------- Feature 6


def _assigned_bus_note(result: StudentBusOptions) -> str | None:
    bus_id = result.assignment.bus.id
    stop = result.assignment.boarding_stop.name
    if result.assigned_option is not None:
        return None
    if result.my_bus is None:
        return f"No live data for bus {bus_id} yet."
    sb, p = result.my_bus
    if p is None:
        return f"Bus {bus_id} is running {sb.position.direction.label} — not serving your stop right now."
    if p.status == "completed":
        return f"Bus {bus_id} has finished this trip."
    return f"Bus {bus_id} has already passed {stop}."


async def _bus_options(c: Container, student_id: str) -> BusOptionsOut:
    result = await c.comparison().for_student(student_id)
    if result is None:
        return BusOptionsOut(
            student_id=student_id,
            status="unassigned",
            boarding_stop=None,
            assigned_bus_id=None,
            route_direction_id=None,
            direction=None,
            assigned_bus_available=False,
            assigned_bus_note=None,
            computed_at=None,
            options=[],
            excluded=[],
        )
    a = result.assignment
    cmp = result.comparison
    names = await c.matching().stop_names([o.sb for o in cmp.options])
    stale_after = c.settings.bus_stale_after_s

    def option(o: BusOption) -> BusOptionOut:
        base = StopBusOut.of(o.sb, names, c.clock, stale_after, assigned_bus_id=a.bus.id)
        return BusOptionOut(
            **base.model_dump(),
            eta=EtaPredictionOut.of(o.prediction),
            occupancy_percentage=o.occupancy_percentage,
            seats_available=o.seats_available,
            crowding=o.crowding,
            delay_minutes=o.delay_minutes,
            comparable=o.comparable,
            indicators=[i.value for i in o.indicators],
            trade_off=o.trade_off,
        )

    return BusOptionsOut(
        student_id=student_id,
        status="assigned",
        boarding_stop=StopSummaryOut(id=a.boarding_stop.id, name=a.boarding_stop.name),
        assigned_bus_id=a.bus.id,
        route_direction_id=a.direction.variant_id,
        direction=a.direction.direction,
        assigned_bus_available=result.assigned_option is not None,
        assigned_bus_note=_assigned_bus_note(result),
        computed_at=result.computed_at,
        options=[option(o) for o in cmp.options],
        excluded=[
            ExcludedBusOut(bus_id=x.sb.bus.id, bus_number=x.sb.bus.id, reason=x.reason) for x in cmp.excluded
        ],
    )


@router.get("/students/me/bus-options", response_model=BusOptionsOut)
async def my_bus_options(principal: Student, c: Container) -> BusOptionsOut:
    """Compare the buses serving the student's ASSIGNED boarding stop and direction.

    Information only: indicators (FASTEST / LEAST_CROWDED / ASSIGNED / BEST_ALTERNATIVE)
    explain trade-offs; the college assignment never changes here.
    """
    return await _bus_options(c, principal.user_id)


@router.get("/students/{student_id}/bus-options", response_model=BusOptionsOut)
async def student_bus_options(student_id: str, principal: CurrentPrincipal, c: Container) -> BusOptionsOut:
    """Same comparison for a given student: the student themself, or an admin.

    Another student gets 403 whether or not the id exists (no probing of assignments).
    """
    if principal.role is Role.STUDENT and principal.user_id != student_id:
        raise ForbiddenError("students can only view their own bus options")
    if principal.role not in (Role.STUDENT, Role.ADMIN):
        raise ForbiddenError("requires role: student (own) or admin")
    user = await c.repos.users.get(student_id)
    if user is None or user.role is not Role.STUDENT:
        raise NotFoundError(f"student {student_id} not found")
    return await _bus_options(c, student_id)
