"""The committed synthetic world: integrity, shared stops, directions, determinism."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pytest

from app.core.clock import DEFAULT_TZ
from app.core.config import BACKEND_DIR
from app.models.common import Direction, Role
from app.seed import SeedBundle, build_trips, load_seed, shared_stops, validate_bundle
from app.seed.loader import scheduled_offsets


def test_seed_has_no_problems(bundle: SeedBundle):
    assert validate_bundle(bundle, DEFAULT_TZ) == []


def test_counts_match_spec(bundle: SeedBundle):
    assert len(bundle.routes) == 6
    assert 35 <= len(bundle.stops) <= 40
    assert len(bundle.buses) == 12 and len(bundle.drivers) == 12
    roles = Counter(u.role for u in bundle.users)
    assert roles[Role.STUDENT] == 300 and roles[Role.ADMIN] == 2 and roles[Role.DRIVER] == 12


def test_shared_stops_support_comparison_and_recovery(bundle: SeedBundle):
    shared = shared_stops(bundle)
    assert 5 <= len(shared) <= 6
    sizes = Counter(len(v) for v in shared.values())
    assert sizes[2] >= 1 and sizes[3] >= 1  # some by 2 routes, some by 3


def test_twelve_directions_from_six_physical_routes(bundle: SeedBundle):
    variants = sorted(d.variant_id for r in bundle.routes for d in r.directions)
    assert variants == sorted([f"R{i}" for i in range(1, 7)] + [f"R{i}-E" for i in range(1, 7)])


def test_evening_reuses_geometry_in_reverse(bundle: SeedBundle):
    for r in bundle.routes:
        to = r.direction(Direction.TO_CAMPUS)
        frm = r.direction(Direction.FROM_CAMPUS)
        assert frm.stop_ids == list(reversed(to.stop_ids))
        fwd, rev = r.polyline(Direction.TO_CAMPUS), r.polyline(Direction.FROM_CAMPUS)
        assert rev.coords == tuple(reversed(fwd.coords))
        for a, b in zip(to.stops, reversed(frm.stops)):
            assert b.distance_along_m == pytest.approx(r.length_m - a.distance_along_m, abs=0.02)


def test_stops_lie_on_their_routes(bundle: SeedBundle):
    for r in bundle.routes:
        for d in r.directions:
            line = r.polyline(d.direction)
            for rs in d.stops:
                proj = line.project(bundle.stop(rs.stop_id).location.lnglat)
                assert proj.offset_m <= 50, (r.id, rs.stop_id)


def test_segment_class_lookup_is_direction_aware(bundle: SeedBundle):
    r3 = bundle.route("R3")  # OMR is declared highway between Tidel Park and Sholinganallur
    to = r3.direction(Direction.TO_CAMPUS)
    mid_omr = (to.stop("S20").distance_along_m + to.stop("S27").distance_along_m) / 2
    assert r3.segment_class_at(mid_omr, Direction.TO_CAMPUS) == "highway"
    assert r3.segment_class_at(r3.length_m - mid_omr, Direction.FROM_CAMPUS) == "highway"


def test_seed_is_deterministic():
    a = load_seed(BACKEND_DIR / "data" / "seed", 42)
    b = load_seed(BACKEND_DIR / "data" / "seed", 42)
    c = load_seed(BACKEND_DIR / "data" / "seed", 7)
    assert [p.model_dump() for p in a.student_profiles] == [p.model_dump() for p in b.student_profiles]
    assert [p.home_stop_id for p in a.student_profiles] != [p.home_stop_id for p in c.student_profiles]
    assert a.buses[0].qr_secret == b.buses[0].qr_secret != c.buses[0].qr_secret


def test_trips_for_a_service_date(bundle: SeedBundle):
    trips = build_trips(bundle.schedule, bundle.buses, date(2026, 10, 5), DEFAULT_TZ)
    assert len(trips) == 24  # 12 buses × (morning + evening)
    assert {t.direction for t in trips} == set(Direction)
    first = trips[0]
    assert first.id == "T-20261005-R1-0715"
    assert first.scheduled_start.utcoffset() == timedelta(0)
    assert first.scheduled_start.astimezone(DEFAULT_TZ).strftime("%H:%M") == "07:15"
    per_route = Counter(t.route_id for t in trips if t.direction is Direction.TO_CAMPUS)
    assert all(n >= 2 for n in per_route.values())  # "my bus" + "other buses on my route"


def test_scheduled_offsets():
    # 0 m, 600 m, 1200 m at 6 m/s with 30 s dwell at the intermediate stop
    assert scheduled_offsets([0, 600, 1200], [0, 30, 0], 6.0) == [0, 100, 230]
