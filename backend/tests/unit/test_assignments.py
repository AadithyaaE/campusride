"""College-assigned bus: validation rules and the deterministic seed allocation."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import pytest

from app.core.config import BACKEND_DIR
from app.core.errors import ConflictError
from app.models.common import FleetStatus
from app.seed import SeedBundle, load_seed
from app.services.assignments import AssignmentService, new_assignment, validate_assignment

AT = datetime(2026, 6, 1, 4, 30, tzinfo=UTC)


def check(bundle: SeedBundle, student: str, bus: str, variant: str, stop: str) -> list[str]:
    a = new_assignment(student, bus, variant, stop, by="admin", at=AT)
    users = {u.id: u for u in bundle.users}
    buses = {b.id: b for b in bundle.buses}
    return validate_assignment(a, student=users.get(student), bus=buses.get(bus), routes=bundle.routes)


def test_valid_assignment(bundle: SeedBundle):
    # B03 runs R2; Medavakkam (S08) is served by R2 to campus.
    assert check(bundle, "U-S0001", "B03", "R2", "S08") == []


@pytest.mark.parametrize(
    ("student", "bus", "variant", "stop", "message"),
    [
        ("U-S0001", "B01", "R2", "S08", "runs route R1, not R2"),  # bus not on that route
        ("U-S0001", "B03", "R2", "S01", "not served by R2"),  # stop not on the route
        ("U-S0001", "B03", "R2", "S00", "final stop of R2"),  # can't board at the terminus
        ("U-S0001", "B99", "R2", "S08", "bus B99 does not exist"),
        ("U-S0001", "B03", "R9", "S08", "route direction R9 does not exist"),
        ("U-NOPE", "B03", "R2", "S08", "student U-NOPE does not exist"),
        ("U-A01", "B03", "R2", "S08", "is not a student"),
    ],
)
def test_invalid_assignments(bundle, student, bus, variant, stop, message):
    assert any(message in p for p in check(bundle, student, bus, variant, stop))


def test_evening_direction_boards_at_campus(bundle: SeedBundle):
    assert check(bundle, "U-S0001", "B03", "R2-E", "S00") == []
    assert any("final stop" in p for p in check(bundle, "U-S0001", "B03", "R2-E", "S09"))


def test_bus_out_of_service_rejected(bundle: SeedBundle):
    bus = bundle.buses[0].model_copy(update={"status": FleetStatus.MAINTENANCE})
    a = new_assignment("U-S0001", bus.id, "R1", "S01", by="admin", at=AT)
    users = {u.id: u for u in bundle.users}
    assert any(
        "not in active service" in p
        for p in validate_assignment(a, student=users["U-S0001"], bus=bus, routes=bundle.routes)
    )


def test_seed_assignments_are_valid_balanced_and_within_capacity(bundle: SeedBundle):
    capacity = {b.id: b.capacity for b in bundle.buses}
    load = Counter(a.assigned_bus_id for a in bundle.student_assignments)
    assert set(load) == set(capacity)  # every bus carries students
    assert all(load[b] <= capacity[b] for b in load)
    homes = {p.id: p.home_stop_id for p in bundle.student_profiles}
    assert all(a.boarding_stop_id == homes[a.id] for a in bundle.student_assignments)
    assert all(
        a.assigned_route_direction_id.startswith("R") and not a.assigned_route_direction_id.endswith("-E")
        for a in bundle.student_assignments
    )


def test_some_students_await_assignment(bundle: SeedBundle):
    assigned = {a.id for a in bundle.student_assignments}
    unassigned = sorted(p.id for p in bundle.student_profiles if p.id not in assigned)
    assert unassigned == [f"U-S{i:04d}" for i in range(25, 301, 25)]


def test_seed_assignments_are_deterministic():
    a = load_seed(BACKEND_DIR / "data" / "seed", 42).student_assignments
    b = load_seed(BACKEND_DIR / "data" / "seed", 42).student_assignments
    assert [x.model_dump() for x in a] == [x.model_dump() for x in b]


async def test_service_resolves_and_guards_writes(container):
    svc = AssignmentService(container.repos)
    resolved = await svc.for_student("U-S0001")
    assert resolved is not None and resolved.bus.default_route_id == resolved.route.id
    assert await svc.for_student("U-S0025") is None  # awaiting assignment

    with pytest.raises(ConflictError, match="runs route R1"):
        await svc.assign(new_assignment("U-S0025", "B01", "R2", "S08", by="admin", at=AT))
    await svc.assign(new_assignment("U-S0025", "B03", "R2", "S08", by="admin", at=AT))
    now = await svc.for_student("U-S0025")
    assert now is not None and (now.bus.id, now.boarding_stop.id) == ("B03", "S08")
