"""Seed integrity rules. ``validate_bundle`` returns human-readable problems (empty = OK)."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.geo import project_point
from app.models.common import Direction, Role
from app.seed.loader import STOP_MAX_OFFSET_M, SeedBundle
from app.seed.trips import build_trips
from app.services.assignments import validate_assignment

EXPECTED = {
    "routes": (6, 6),
    "stops": (35, 40),
    "buses": (12, 12),
    "drivers": (12, 12),
    "admins": (2, 2),
    "students": (300, 300),
    "shared_stops": (5, 6),
}
MIN_BUSES_PER_ROUTE = 2


def _in(name: str, value: int, problems: list[str]) -> None:
    lo, hi = EXPECTED[name]
    if not lo <= value <= hi:
        problems.append(f"{name}: expected {lo}–{hi}, found {value}")


def shared_stops(bundle: SeedBundle) -> dict[str, list[str]]:
    """Non-terminal stops served by more than one physical route → route ids."""
    out: dict[str, list[str]] = {}
    for stop in bundle.stops:
        if stop.is_campus_terminal:
            continue
        routes = sorted(r.id for r in bundle.routes if r.serves(stop.id))
        if len(routes) > 1:
            out[stop.id] = routes
    return out


def validate_bundle(bundle: SeedBundle, tz: ZoneInfo | None = None) -> list[str]:
    problems: list[str] = []
    tz = tz or ZoneInfo(bundle.campus.timezone)
    stops = {s.id: s for s in bundle.stops}
    routes = {r.id: r for r in bundle.routes}
    buses = {b.id: b for b in bundle.buses}
    drivers = {d.id: d for d in bundle.drivers}
    users = {u.id: u for u in bundle.users}

    # --- unique ids
    for kind, items in (
        ("stop", bundle.stops),
        ("route", bundle.routes),
        ("bus", bundle.buses),
        ("driver", bundle.drivers),
        ("user", bundle.users),
    ):
        dupes = [i for i, n in Counter(x.id for x in items).items() if n > 1]
        if dupes:
            problems.append(f"duplicate {kind} ids: {dupes}")
    dup_emails = [e for e, n in Counter(u.email for u in bundle.users).items() if n > 1]
    if dup_emails:
        problems.append(f"duplicate emails: {dup_emails[:5]}")

    # --- counts
    _in("routes", len(bundle.routes), problems)
    _in("stops", len(bundle.stops), problems)
    _in("buses", len(bundle.buses), problems)
    _in("drivers", len(bundle.drivers), problems)
    _in("admins", sum(u.role is Role.ADMIN for u in bundle.users), problems)
    _in("students", len(bundle.student_profiles), problems)

    # --- campus terminal
    terminals = [s.id for s in bundle.stops if s.is_campus_terminal]
    if len(terminals) != 1:
        problems.append(f"expected exactly one campus terminal stop, found {terminals}")

    # --- routes: geometry, stops, directions
    for r in bundle.routes:
        to = r.direction(Direction.TO_CAMPUS)
        frm = r.direction(Direction.FROM_CAMPUS)
        if terminals and to.stops[-1].stop_id != terminals[0]:
            problems.append(f"{to.variant_id}: must end at the campus terminal")
        if terminals and frm.stops[0].stop_id != terminals[0]:
            problems.append(f"{frm.variant_id}: must start at the campus terminal")
        if frm.stop_ids != list(reversed(to.stop_ids)):
            problems.append(f"{r.id}: evening stops must be the morning stops reversed")
        for a, b in zip(to.stops, reversed(frm.stops)):
            if abs((r.length_m - a.distance_along_m) - b.distance_along_m) > 0.05:
                problems.append(f"{r.id}: {a.stop_id} evening distance must equal length − morning distance")
        for a, b in zip(to.stops, to.stops[1:]):
            if b.distance_along_m <= a.distance_along_m:
                problems.append(
                    f"{to.variant_id}: stop distances must strictly increase ({a.stop_id}→{b.stop_id})"
                )
        line = r.polyline(Direction.TO_CAMPUS)
        for rs in to.stops:
            stop = stops.get(rs.stop_id)
            if stop is None:
                problems.append(f"{r.id}: unknown stop {rs.stop_id}")
                continue
            off = project_point(line.coords, line.cum, stop.location.lnglat).offset_m
            if off > STOP_MAX_OFFSET_M:
                problems.append(f"{r.id}: stop {rs.stop_id} is {off:.0f} m from the route")

    unused = [s.id for s in bundle.stops if not any(r.serves(s.id) for r in bundle.routes)]
    if unused:
        problems.append(f"stops not served by any route: {unused}")

    # --- shared stops (needed for multi-bus comparison and recovery)
    shared = shared_stops(bundle)
    _in("shared_stops", len(shared), problems)
    if not any(len(v) >= 3 for v in shared.values()):
        problems.append("at least one stop should be shared by 3 routes")

    # --- fleet & people references
    for b in bundle.buses:
        if b.default_route_id not in routes:
            problems.append(f"bus {b.id}: unknown route {b.default_route_id}")
        if b.driver_id and b.driver_id not in drivers:
            problems.append(f"bus {b.id}: unknown driver {b.driver_id}")
    for d in bundle.drivers:
        if d.user_id not in users or users[d.user_id].role is not Role.DRIVER:
            problems.append(f"driver {d.id}: missing driver user {d.user_id}")
    for p in bundle.student_profiles:
        u = users.get(p.id)
        if u is None or u.role is not Role.STUDENT:
            problems.append(f"profile {p.id}: missing student user")
        if p.home_stop_id not in stops or stops[p.home_stop_id].is_campus_terminal:
            problems.append(f"profile {p.id}: invalid home stop {p.home_stop_id}")

    # --- college/admin bus assignments
    student_ids = {p.id for p in bundle.student_profiles}
    load: dict[str, int] = {}
    for a in bundle.student_assignments:
        issues = validate_assignment(
            a, student=users.get(a.id), bus=buses.get(a.assigned_bus_id), routes=bundle.routes
        )
        problems.extend(f"assignment {a.id}: {issue}" for issue in issues)
        load[a.assigned_bus_id] = load.get(a.assigned_bus_id, 0) + 1
    dupes = [i for i, n in Counter(a.id for a in bundle.student_assignments).items() if n > 1]
    if dupes:
        problems.append(f"students with more than one assignment: {dupes[:5]}")
    for bus_id, n in load.items():
        if bus_id in buses and n > buses[bus_id].capacity:
            problems.append(f"bus {bus_id}: {n} students assigned, capacity {buses[bus_id].capacity}")
    unassigned = student_ids - {a.id for a in bundle.student_assignments}
    if not unassigned:
        problems.append("expected some unassigned (new) students for the demo")
    if len(unassigned) > len(student_ids) // 10:
        problems.append(f"too many unassigned students: {len(unassigned)}")

    # --- schedule
    for route_id, n in Counter(b.default_route_id for b in bundle.buses).items():
        if n < MIN_BUSES_PER_ROUTE:
            problems.append(f"route {route_id}: needs at least {MIN_BUSES_PER_ROUTE} buses, has {n}")
    for st in bundle.schedule.trips:
        if st.bus_id not in buses:
            problems.append(f"schedule: unknown bus {st.bus_id}")
        if st.route_id not in routes:
            problems.append(f"schedule: unknown route {st.route_id}")
    if problems:
        return problems  # trip checks below assume valid references

    probe_date = date(2026, 1, 5)  # any weekday; the checks depend only on time of day
    trips = build_trips(bundle.schedule, bundle.buses, probe_date, tz)
    by_bus: dict[str, list[tuple[datetime, datetime, str]]] = {}
    for t in trips:
        variant = routes[t.route_id].variant(t.variant_id)
        start = t.scheduled_start
        end = start + timedelta(seconds=variant.stops[-1].scheduled_offset_s)
        lo, hi = bundle.schedule.windows[t.direction]
        local_start, local_end = start.astimezone(tz).time(), end.astimezone(tz).time()
        if not (lo <= local_start and local_end <= hi):
            problems.append(
                f"{t.id}: runs {local_start:%H:%M}–{local_end:%H:%M}, outside window {lo:%H:%M}–{hi:%H:%M}"
            )
        by_bus.setdefault(t.bus_id, []).append((start, end, t.id))
    for bus_id, spans in by_bus.items():
        spans.sort()
        for (_s1, e1, a), (s2, _e2, b) in zip(spans, spans[1:]):
            if s2 < e1:
                problems.append(f"bus {bus_id}: trips {a} and {b} overlap")
        directions = {t.direction for t in trips if t.bus_id == bus_id}
        if directions != set(Direction):
            problems.append(f"bus {bus_id}: needs one morning and one evening trip")

    # timezone sanity: all scheduled starts are stored in UTC
    if any(t.scheduled_start.utcoffset() != timedelta(0) for t in trips):
        problems.append("trip scheduled_start must be UTC")
    return problems
