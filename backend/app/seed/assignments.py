"""Deterministic college/admin bus assignments for the synthetic students.

Stands in for the transport office's allocation until an admin UI exists:

* boarding stop = the student's (generated) home stop,
* direction     = TO_CAMPUS (the morning trip; the same bus brings them home
                  on its FROM_CAMPUS trip),
* bus           = the least-loaded active bus among the routes serving that
                  stop, never above bus capacity (ties → lowest bus id).

Every ``unassigned_every``-th student (student025, student050, …) is left
WITHOUT an assignment to represent newly enrolled students the office has not
processed yet. No randomness is involved, so the result depends only on the
seed files and SEED (through the generated home stops).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models import Bus, Route, StudentAssignment, StudentProfile
from app.models.common import Direction, FleetStatus
from app.services.assignments import new_assignment


def generate_assignments(
    config: dict[str, Any],
    profiles: list[StudentProfile],
    buses: list[Bus],
    routes: list[Route],
) -> list[StudentAssignment]:
    every = int(config["unassigned_every"])
    at = datetime.fromisoformat(config["assigned_at"])
    load = {b.id: 0 for b in buses}
    active = sorted((b for b in buses if b.status is FleetStatus.ACTIVE), key=lambda b: b.id)

    out: list[StudentAssignment] = []
    for index, profile in enumerate(sorted(profiles, key=lambda p: p.id), start=1):
        if every and index % every == 0:
            continue  # "new student" — awaiting assignment by the transport office
        candidates: list[tuple[int, str, str]] = []
        for route in routes:
            to_campus = route.direction(Direction.TO_CAMPUS)
            rs = to_campus.stop(profile.home_stop_id)
            if rs is None or rs.seq == len(to_campus.stops) - 1:
                continue
            for bus in active:
                if bus.default_route_id == route.id and load[bus.id] < bus.capacity:
                    candidates.append((load[bus.id], bus.id, to_campus.variant_id))
        if not candidates:
            continue  # no capacity left on any serving bus: stays unassigned
        _, bus_id, variant_id = min(candidates)
        load[bus_id] += 1
        out.append(new_assignment(profile.id, bus_id, variant_id, profile.home_stop_id, by="seed", at=at))
    return out
