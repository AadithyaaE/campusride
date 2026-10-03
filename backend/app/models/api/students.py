"""DTOs for the student's (read-only) college-assigned transport."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models import GeoPoint
from app.models.common import Direction
from app.services.assignments import ResolvedAssignment


class AssignedBusOut(BaseModel):
    id: str
    reg_no: str


class AssignedRouteOut(BaseModel):
    route_id: str
    route_direction_id: str
    """Route variant id, e.g. ``R2`` / ``R2-E``."""
    direction: Direction
    label: str
    name: str
    color: str


class BoardingStopOut(BaseModel):
    stop_id: str
    name: str
    location: GeoPoint
    seq: int
    """Position of the stop on the route direction (0-based)."""
    stop_count: int
    scheduled_offset_s: int
    """Timetable offset from the route direction's first stop (not an ETA)."""


class AssignmentOut(BaseModel):
    bus: AssignedBusOut
    route: AssignedRouteOut
    boarding_stop: BoardingStopOut
    assigned_at: datetime

    @classmethod
    def of(cls, r: ResolvedAssignment) -> AssignmentOut:
        return cls(
            bus=AssignedBusOut(id=r.bus.id, reg_no=r.bus.reg_no),
            route=AssignedRouteOut(
                route_id=r.route.id,
                route_direction_id=r.direction.variant_id,
                direction=r.direction.direction,
                label=r.direction.label,
                name=r.route.name,
                color=r.route.color,
            ),
            boarding_stop=BoardingStopOut(
                stop_id=r.boarding_stop.id,
                name=r.boarding_stop.name,
                location=r.boarding_stop.location,
                seq=r.route_stop.seq,
                stop_count=len(r.direction.stops),
                scheduled_offset_s=r.route_stop.scheduled_offset_s,
            ),
            assigned_at=r.assignment.assigned_at,
        )


class MyAssignmentOut(BaseModel):
    student_id: str
    status: Literal["assigned", "unassigned"]
    assignment: AssignmentOut | None
    """``None`` until the college assigns a bus."""
