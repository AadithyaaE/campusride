"""Deterministic synthetic students.

Every random choice comes from ``derive_seed(SEED, "students")``, so the
same SEED always yields the same 300 students, names and home stops.
"""

from __future__ import annotations

import random
from typing import Any

from app.core.clock import derive_seed
from app.models import Route, Stop, StudentProfile, User
from app.models.common import Role


def generate_students(
    config: dict[str, Any], stops: list[Stop], routes: list[Route], seed: int
) -> tuple[list[User], list[StudentProfile]]:
    rng = random.Random(derive_seed(seed, "students"))
    candidates = sorted((s for s in stops if not s.is_campus_terminal), key=lambda s: s.id)
    weights = [float(config["stop_weights"].get(s.id, config["default_stop_weight"])) for s in candidates]
    serving: dict[str, list[str]] = {
        s.id: sorted({r.id for r in routes for d in r.directions if d.stop(s.id)}) for s in candidates
    }
    lo, hi = config["walk_speed_mps"]

    users: list[User] = []
    profiles: list[StudentProfile] = []
    for i in range(1, int(config["count"]) + 1):
        first = rng.choice(config["first_names"])
        last = rng.choice(config["last_names"])
        stop = rng.choices(candidates, weights=weights, k=1)[0]
        walk = round(rng.uniform(lo, hi), 2)
        uid = f"U-S{i:04d}"
        users.append(
            User(
                id=uid,
                role=Role.STUDENT,
                name=f"{first} {last}",
                email=f"student{i:03d}@{config['email_domain']}",
            )
        )
        profiles.append(
            StudentProfile(
                id=uid,
                roll_no=f"{config['roll_prefix']}{i:04d}",
                home_stop_id=stop.id,
                preferred_route_ids=serving[stop.id],
                walk_speed_mps=walk,
            )
        )
    return users, profiles
