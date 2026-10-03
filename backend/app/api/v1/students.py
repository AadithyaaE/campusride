"""Student self-service — read-only. Transport assignments are set by the college/admin."""

from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import Principal
from app.core.errors import ForbiddenError, NotFoundError
from app.deps import Container, CurrentPrincipal, Repos, require_role
from app.models import GeoPoint
from app.models.api.commute import CommuteDecisionOut, StudentLocationOut
from app.models.api.comparison import BusOptionOut, BusOptionsOut, ExcludedBusOut
from app.models.api.eta import ArrivalOut, EtaPredictionOut, MyArrivalsOut
from app.models.api.matching import MyStopBusesOut, StopBusOut, StopSummaryOut
from app.models.api.students import AssignmentOut, MyAssignmentOut
from app.models.common import Role
from app.services.assignments import AssignmentService
from app.services.bus_comparison_service import BusOption, StudentBusOptions
from app.services.commute_decision_service import StudentCommute

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
    await _authorize_student_view(principal, c, student_id)
    return await _bus_options(c, student_id)


async def _authorize_student_view(principal: Principal, c: Container, student_id: str) -> None:
    """The student themself, or an admin. Other students: 403 (even for unknown ids)."""
    if principal.role is Role.STUDENT and principal.user_id != student_id:
        raise ForbiddenError("students can only view their own transport information")
    if principal.role not in (Role.STUDENT, Role.ADMIN):
        raise ForbiddenError("requires role: student (own) or admin")
    user = await c.repos.users.get(student_id)
    if user is None or user.role is not Role.STUDENT:
        raise NotFoundError(f"student {student_id} not found")


# --------------------------------------------------------------------------- Feature 7


def _commute_out(c: Container, student_id: str, sc: StudentCommute | None) -> CommuteDecisionOut:
    buffer_min = round(c.settings.commute_safety_buffer_s / 60)
    if sc is None:
        return CommuteDecisionOut(
            student_id=student_id,
            status="unassigned",
            decision=None,
            reason="Your bus assignment is not available yet.",
            bus_id=None,
            bus_number=None,
            route_direction_id=None,
            boarding_stop=None,
            student_location=None,
            walking_distance_m=None,
            walking_speed_mps=None,
            walking_time_minutes=None,
            bus_eta_minutes=None,
            bus_arrival_time=None,
            required_arrival_time=None,
            student_arrival_time=None,
            safety_buffer_minutes=buffer_min,
            spare_minutes=None,
            delay_minutes=None,
            bus_status=None,
            proximity=None,
            stale=False,
            eta=None,
            alternatives_available=0,
            computed_at=c.clock.now(),
        )
    a, r, sb = sc.assignment, sc.result, sc.my_bus
    loc = sc.location
    return CommuteDecisionOut(
        student_id=student_id,
        status="assigned",
        decision=r.decision,
        reason=r.reason,
        bus_id=a.bus.id,
        bus_number=a.bus.id,
        route_direction_id=a.direction.variant_id,
        boarding_stop=StopSummaryOut(id=a.boarding_stop.id, name=a.boarding_stop.name),
        student_location=(
            StudentLocationOut(location=GeoPoint.of(*loc.point), source=loc.source, label=loc.label)
            if loc is not None
            else None
        ),
        walking_distance_m=None if r.walking_distance_m is None else round(r.walking_distance_m),
        walking_speed_mps=None if r.walking_speed_mps is None else round(r.walking_speed_mps, 2),
        walking_time_minutes=r.walking_time_minutes,
        bus_eta_minutes=r.bus_eta_minutes,
        bus_arrival_time=r.bus_arrival_time,
        required_arrival_time=r.required_arrival_time,
        student_arrival_time=r.student_arrival_time,
        safety_buffer_minutes=buffer_min,
        spare_minutes=None if r.spare_s is None else math.floor(r.spare_s / 60),
        delay_minutes=None if sb is None else round(sb.state.delay_s / 60),
        bus_status=None if sb is None else sb.state.status,
        proximity=None if sb is None or sb.match is None else sb.match.proximity,
        stale=sc.stale,
        eta=None if sc.prediction is None else EtaPredictionOut.of(sc.prediction),
        alternatives_available=sc.alternatives_available,
        computed_at=r.computed_at,
    )


@router.get("/students/me/commute-decision", response_model=CommuteDecisionOut)
async def my_commute_decision(principal: Student, c: Container) -> CommuteDecisionOut:
    """ "Will I make my bus?" for the student's ASSIGNED bus and boarding stop.

    Deterministic rules (no ML, no probability). Everything is derived from the
    assignment — the caller cannot substitute a bus or stop.
    """
    return _commute_out(c, principal.user_id, await c.commute().for_student(principal.user_id))


@router.get("/students/{student_id}/commute-decision", response_model=CommuteDecisionOut)
async def student_commute_decision(
    student_id: str, principal: CurrentPrincipal, c: Container
) -> CommuteDecisionOut:
    """Same decision for a given student: the student themself, or an admin."""
    await _authorize_student_view(principal, c, student_id)
    return _commute_out(c, student_id, await c.commute().for_student(student_id))
