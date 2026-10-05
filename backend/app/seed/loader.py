"""Build domain models from the committed seed files (``backend/data/seed``).

Hand-authored: campus, buses, drivers, admins, schedules, traffic profiles.
Authored once via OSRM (``scripts/author_routes.py``): stops.geojson, routes.geojson.
Generated here, deterministically from SEED: students, QR secrets, the
FROM_CAMPUS variants, stop distances and scheduled offsets.

Nothing in this module talks to the network or the database.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

from app.core.ids import variant_id
from app.geo import Polyline, stop_distances
from app.models import (
    Bus,
    Campus,
    Driver,
    GeoPoint,
    LineString,
    Route,
    RouteDirection,
    RouteStop,
    Stop,
    StudentAssignment,
    StudentProfile,
    TrafficProfile,
    User,
)
from app.models.common import BusSource, Direction, Role, SegmentClass

STOP_MAX_OFFSET_M = 50.0
"""A stop must lie within this distance of every route that serves it."""

DIRECTION_LABEL = {Direction.TO_CAMPUS: "To Campus", Direction.FROM_CAMPUS: "From Campus"}


@dataclass(frozen=True)
class ScheduledTrip:
    bus_id: str
    route_id: str
    direction: Direction
    departure: time


@dataclass
class Schedule:
    schedule_speed_kmph: float
    windows: dict[Direction, tuple[time, time]]
    trips: list[ScheduledTrip]


@dataclass
class SeedBundle:
    seed: int
    campus: Campus
    stops: list[Stop]
    routes: list[Route]
    buses: list[Bus]
    drivers: list[Driver]
    users: list[User]
    student_profiles: list[StudentProfile]
    student_assignments: list[StudentAssignment]
    traffic_profiles: list[TrafficProfile]
    schedule: Schedule
    meta: dict[str, Any] = field(default_factory=dict)

    def stop(self, stop_id: str) -> Stop:
        return next(s for s in self.stops if s.id == stop_id)

    def route(self, route_id: str) -> Route:
        return next(r for r in self.routes if r.id == route_id)


def _read(seed_dir: Path, name: str) -> Any:
    return json.loads((seed_dir / name).read_text(encoding="utf-8"))


def _hhmm(text: str) -> time:
    return time.fromisoformat(text)


def qr_secret(seed: int, bus_id: str) -> str:
    return hashlib.blake2b(f"{seed}|qr|{bus_id}".encode(), digest_size=16).hexdigest()


def expand_rle(runs: list[list[Any]]) -> list[SegmentClass]:
    out: list[SegmentClass] = []
    for value, count in runs:
        out.extend([SegmentClass(value)] * int(count))
    return out


def scheduled_offsets(distances: list[float], dwells: list[int], speed_mps: float) -> list[int]:
    """Scheduled arrival offsets: travel at ``speed_mps`` plus dwell at each
    intermediate stop. The first stop is the departure point (offset 0)."""
    offsets = [0]
    t = 0.0
    for i in range(1, len(distances)):
        if i > 1:
            t += dwells[i - 1]
        t += (distances[i] - distances[i - 1]) / speed_mps
        offsets.append(round(t))
    return offsets


def build_route(feature: dict[str, Any], stops_by_id: dict[str, Stop], schedule_speed_kmph: float) -> Route:
    props = feature["properties"]
    rid = props["id"]
    line = Polyline.from_coords(feature["geometry"]["coordinates"])
    stop_specs = props["stops"]
    stop_ids = [s["stop_id"] for s in stop_specs]
    dwells = [int(s["dwell_s"]) for s in stop_specs]
    missing = [sid for sid in stop_ids if sid not in stops_by_id]
    if missing:
        raise ValueError(f"route {rid} references unknown stops {missing}")

    projections = stop_distances(
        line.coords,
        line.cum,
        [stops_by_id[sid].location.lnglat for sid in stop_ids],
        max_offset_m=STOP_MAX_OFFSET_M,
    )
    speed = schedule_speed_kmph / 3.6

    def direction(d: Direction, ids: list[str], dist: list[float], dw: list[int]) -> RouteDirection:
        offs = scheduled_offsets(dist, dw, speed)
        vid = variant_id(rid, d)
        return RouteDirection(
            variant_id=vid,
            direction=d,
            label=f"{vid} — {DIRECTION_LABEL[d]}",
            stops=[
                RouteStop(
                    stop_id=sid,
                    seq=i,
                    distance_along_m=round(dist[i], 2),
                    scheduled_offset_s=offs[i],
                    dwell_s=dw[i],
                )
                for i, sid in enumerate(ids)
            ],
        )

    fwd_dist = [p.distance_along_m for p in projections]
    rev_dist = [line.length_m - d for d in reversed(fwd_dist)]
    return Route(
        id=rid,
        name=props["name"],
        color=props["color"],
        campus_id=props["campus_id"],
        path=LineString(coordinates=list(line.coords)),
        cum_dist_m=list(line.cum),
        segment_classes=expand_rle(props["segment_classes"]),
        length_m=line.length_m,
        directions=[
            direction(Direction.TO_CAMPUS, stop_ids, fwd_dist, dwells),
            direction(Direction.FROM_CAMPUS, list(reversed(stop_ids)), rev_dist, list(reversed(dwells))),
        ],
    )


def load_schedule(seed_dir: Path) -> Schedule:
    """The daily trip schedule (``schedules.json``) — also used by the simulator."""
    sched_raw = _read(seed_dir, "schedules.json")
    return Schedule(
        schedule_speed_kmph=float(sched_raw["schedule_speed_kmph"]),
        windows={Direction(k): (_hhmm(v[0]), _hhmm(v[1])) for k, v in sched_raw["windows"].items()},
        trips=[
            ScheduledTrip(t["bus_id"], t["route_id"], Direction(t["direction"]), _hhmm(t["departure"]))
            for t in sched_raw["trips"]
        ],
    )


SEED_IDENTITY_TIME = datetime(2026, 6, 1, tzinfo=UTC)
"""Deterministic ``created_at`` / ``updated_at`` of the seeded identities (Feature 15)."""


def load_seed(seed_dir: Path, seed: int) -> SeedBundle:
    # local imports: these modules depend on this one
    from app.seed.assignments import generate_assignments
    from app.seed.students import generate_students

    campus_raw = _read(seed_dir, "campus.json")
    campus = Campus(
        id=campus_raw["id"],
        name=campus_raw["name"],
        short_name=campus_raw["short_name"],
        location=GeoPoint(coordinates=tuple(campus_raw["location"])),
        timezone=campus_raw["timezone"],
    )

    stops = [
        Stop(
            id=f["properties"]["id"],
            name=f["properties"]["name"],
            location=GeoPoint(coordinates=tuple(f["geometry"]["coordinates"])),
            campus_id=f["properties"]["campus_id"],
            walk_radius_m=f["properties"].get("walk_radius_m", 400),
            is_campus_terminal=f["properties"].get("is_campus_terminal", False),
        )
        for f in _read(seed_dir, "stops.geojson")["features"]
    ]
    stops_by_id = {s.id: s for s in stops}

    schedule = load_schedule(seed_dir)

    routes = [
        build_route(f, stops_by_id, schedule.schedule_speed_kmph)
        for f in _read(seed_dir, "routes.geojson")["features"]
    ]

    drivers_raw = _read(seed_dir, "drivers.json")
    drivers = [
        Driver(
            id=d["id"], user_id=f"U-{d['id']}", name=d["name"], phone=d["phone"], license_no=d["license_no"]
        )
        for d in drivers_raw
    ]
    users = [User(id=f"U-{d['id']}", role=Role.DRIVER, name=d["name"], email=d["email"]) for d in drivers_raw]
    users += [
        User(id=a["id"], role=Role.ADMIN, name=a["name"], email=a["email"])
        for a in _read(seed_dir, "admins.json")
    ]

    buses = [
        Bus(
            id=b["id"],
            reg_no=b["reg_no"],
            capacity=b["capacity"],
            qr_secret=qr_secret(seed, b["id"]),
            default_route_id=b["default_route_id"],
            driver_id=b.get("driver_id"),
            source=BusSource(b.get("source", "sim")),
        )
        for b in _read(seed_dir, "buses.json")
    ]

    traffic = [TrafficProfile.model_validate(t) for t in _read(seed_dir, "traffic_profiles.json")]

    students_cfg = _read(seed_dir, "students.json")
    student_users, profiles = generate_students(students_cfg, stops, routes, seed)
    assignments = generate_assignments(students_cfg["assignments"], profiles, buses, routes)

    return SeedBundle(
        seed=seed,
        campus=campus,
        stops=stops,
        routes=routes,
        buses=buses,
        drivers=drivers,
        users=[
            u.model_copy(update={"created_at": SEED_IDENTITY_TIME, "updated_at": SEED_IDENTITY_TIME})
            for u in users + student_users
        ],
        student_profiles=profiles,
        student_assignments=assignments,
        traffic_profiles=traffic,
        schedule=schedule,
    )
