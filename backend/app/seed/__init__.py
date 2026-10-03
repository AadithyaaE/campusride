"""Synthetic seed data: load, validate and persist the deterministic demo world."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from app.repositories import Repositories
from app.seed.loader import SeedBundle, load_seed
from app.seed.trips import build_trips
from app.seed.validate import shared_stops, validate_bundle

__all__ = ["SeedBundle", "build_trips", "load_seed", "persist_seed", "shared_stops", "validate_bundle"]


async def persist_seed(
    repos: Repositories, bundle: SeedBundle, service_date: date, tz: ZoneInfo
) -> dict[str, int]:
    """Replace ALL data with the seed world and the trips for ``service_date``.

    Idempotent: running it twice leaves the same state. Runtime collections
    (telemetry, bus states, boardings, deviations, alerts) are cleared too.
    """
    for repo in (
        repos.campuses,
        repos.stops,
        repos.routes,
        repos.buses,
        repos.drivers,
        repos.trips,
        repos.telemetry,
        repos.bus_states,
        repos.users,
        repos.student_profiles,
        repos.student_assignments,
        repos.boarding_events,
        repos.deviations,
        repos.alerts,
        repos.traffic_profiles,
    ):
        await repo.delete_all()

    trips = build_trips(bundle.schedule, bundle.buses, service_date, tz)
    await repos.campuses.insert_many([bundle.campus])
    await repos.stops.insert_many(bundle.stops)
    await repos.routes.insert_many(bundle.routes)
    await repos.buses.insert_many(bundle.buses)
    await repos.drivers.insert_many(bundle.drivers)
    await repos.users.insert_many(bundle.users)
    await repos.student_profiles.insert_many(bundle.student_profiles)
    await repos.student_assignments.insert_many(bundle.student_assignments)
    await repos.traffic_profiles.insert_many(bundle.traffic_profiles)
    await repos.trips.insert_many(trips)
    return {
        "campuses": 1,
        "stops": len(bundle.stops),
        "routes": len(bundle.routes),
        "buses": len(bundle.buses),
        "drivers": len(bundle.drivers),
        "users": len(bundle.users),
        "student_profiles": len(bundle.student_profiles),
        "student_assignments": len(bundle.student_assignments),
        "traffic_profiles": len(bundle.traffic_profiles),
        "trips": len(trips),
    }
