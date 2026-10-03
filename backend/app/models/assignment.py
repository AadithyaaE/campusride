from __future__ import annotations

from pydantic import AwareDatetime

from app.models.common import Document


class StudentAssignment(Document):
    """College/admin-assigned transport for one student (``id`` = the student's user id).

    The ONLY student ↔ transport relationship in CampusRide:

        student → assigned bus → route direction → boarding stop

    Students can read their assignment but never create or change it.
    """

    assigned_bus_id: str
    assigned_route_direction_id: str
    """Route variant id, e.g. ``R2`` (To Campus) or ``R2-E`` (From Campus)."""
    boarding_stop_id: str
    assigned_by: str
    """Who made the assignment: an admin user id, or ``seed`` for synthetic data."""
    assigned_at: AwareDatetime

    @property
    def student_id(self) -> str:
        return self.id
