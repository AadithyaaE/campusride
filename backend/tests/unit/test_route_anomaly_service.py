"""Route deviation (Feature 10): geometry, classification, transitions/alerts, simulator modes."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.geo import LocalFrame
from app.geo.polyline import Polyline
from app.models import GeoPoint
from app.models.common import BusStatus, RouteStatus
from app.services.commute_decision_service import CommuteDecisionService
from app.services.route_anomaly_service import (
    alert_action,
    bus_route_status,
    classify,
    distance_to_route_m,
    evaluate,
)
from app.services.student_location import StudentLocationSource
from app.simulator.deviation import offset_point
from tests.unit.test_bus_comparison import _advance
from tests.unit.test_eta import MIDDAY, make_state

MINOR, MAJOR, STALE_S = 50.0, 150.0, 45.0
ORIGIN = (80.2, 12.9)
F = LocalFrame(ORIGIN)


def line_xy(*pts: tuple[float, float]) -> Polyline:
    """A polyline from local metre coordinates (east, north) around ORIGIN."""
    return Polyline.from_coords([F.to_lnglat(x, y) for x, y in pts])


def dist(line: Polyline, x: float, y: float) -> float:
    return distance_to_route_m(line.coords, line.cum, F.to_lnglat(x, y))[0]


def run(state, route, now=None, **kw):
    return evaluate(
        state, route, now=now or state.ts, stale_after_s=STALE_S, minor_m=MINOR, major_m=MAJOR, **kw
    )


def at(bundle, variant: str, d: float, offset_m: float = 0.0):
    """A tracked state on ``variant`` at ``d`` m along, optionally moved sideways."""
    route = bundle.route(variant.removesuffix("-E"))
    state = make_state(variant, d, ts=MIDDAY)
    line = route.polyline(state.direction)
    p = line.interpolate(d)
    point = offset_point(p.point, p.heading_deg, offset_m, line) if offset_m else p.point
    return state.model_copy(update={"location": GeoPoint.of(*point)}), route


# =========================================================================== geometry


def test_point_on_route_is_zero_and_metric():
    line = line_xy((0, 0), (1000, 0), (1000, 1000))
    assert dist(line, 500, 0) == pytest.approx(0, abs=0.01)
    assert dist(line, 500, 30) == pytest.approx(30, abs=0.1)  # metres, not degrees


def test_multiple_segments_nearest_segment_wins():
    line = line_xy((0, 0), (1000, 0), (1000, 1000), (0, 1000))
    assert dist(line, 1100, 500) == pytest.approx(100, abs=0.2)  # 2nd segment
    assert dist(line, 500, 940) == pytest.approx(60, abs=0.2)  # 3rd segment, not the 1st
    assert dist(line, -30, -40) == pytest.approx(50, abs=0.2)  # beyond an end → vertex


def test_orientation_does_not_matter_and_is_deterministic():
    fwd = line_xy((0, 0), (1000, 0), (1000, 1000))
    rev = line_xy((1000, 1000), (1000, 0), (0, 0))
    for x, y in [(500, 75), (1200, 300), (-10, 5)]:
        assert dist(fwd, x, y) == pytest.approx(dist(rev, x, y), abs=1e-6)
        assert dist(fwd, x, y) == dist(fwd, x, y)


def test_distance_is_to_the_line_not_to_the_nearest_stop():
    line = line_xy((0, 0), (2000, 0))  # "stops" only at the ends
    assert dist(line, 1000, 40) == pytest.approx(40, abs=0.1)  # ~1 km from either stop


# =========================================================================== classification


@pytest.mark.parametrize(
    ("d", "status"),
    [
        (0, RouteStatus.NORMAL),
        (12.0, RouteStatus.NORMAL),  # GPS noise
        (49.9, RouteStatus.NORMAL),
        (50.0, RouteStatus.NORMAL),  # boundary: ≤ minor is NORMAL
        (50.01, RouteStatus.MINOR_DEVIATION),
        (149.99, RouteStatus.MINOR_DEVIATION),
        (150.0, RouteStatus.MAJOR_DEVIATION),  # boundary: ≥ major is MAJOR
        (420.0, RouteStatus.MAJOR_DEVIATION),
    ],
)
def test_classification_boundaries(d, status):
    assert classify(d, minor_m=MINOR, major_m=MAJOR) is status


# ====================================================================== evaluate (authored geometry)


def test_on_route_noise_minor_major_on_real_geometry(bundle):
    for offset, status in [(0, "NORMAL"), (20, "NORMAL"), (100, "MINOR_DEVIATION"), (300, "MAJOR_DEVIATION")]:
        state, route = at(bundle, "R3", 4_000, offset)
        chk = run(state, route)
        assert chk.status.value == status, (offset, chk)
        assert chk.distance_m == pytest.approx(offset, abs=3)


def test_both_directions_of_a_route(bundle):
    to_campus, route = at(bundle, "R3", 4_000, 100)
    back, _ = at(bundle, "R3-E", 4_000, 100)
    assert run(to_campus, route).status is run(back, route).status is RouteStatus.MINOR_DEVIATION


def test_a_different_route_is_far_away(bundle):
    state, _ = at(bundle, "R3", 4_000)
    assert run(state, bundle.route("R1")).status is RouteStatus.MAJOR_DEVIATION


def test_no_trip_completed_no_route_stale_invalid(bundle):
    state, route = at(bundle, "R3", 4_000)
    assert run(None, route, now=MIDDAY).status is RouteStatus.NO_LIVE_DATA
    no_trip = state.model_copy(update={"trip_id": None})
    assert run(no_trip, route).status is RouteStatus.NO_ACTIVE_TRIP
    done = state.model_copy(update={"status": BusStatus.COMPLETED})
    assert run(done, route).status is RouteStatus.NO_ACTIVE_TRIP
    assert run(state, None).status is RouteStatus.NO_ROUTE
    stale = run(state, route, now=state.ts + timedelta(seconds=STALE_S + 1))
    assert stale.status is RouteStatus.STALE and stale.distance_m is None  # never from stale data
    bad = state.model_copy(
        update={"location": GeoPoint.model_construct(type="Point", coordinates=(200.0, 95.0))}
    )
    assert run(bad, route).status is RouteStatus.INVALID_LOCATION


def test_corridor_fast_path_is_exact_for_normal_and_falls_back_otherwise(bundle):
    state, route = at(bundle, "R3", 4_000, 300)
    # a small corridor offset proves NORMAL without scanning; a large one forces the full scan
    assert run(state, route, corridor_offset_m=10).status is RouteStatus.NORMAL
    full = run(state, route, corridor_offset_m=300)
    assert full.status is RouteStatus.MAJOR_DEVIATION and full.nearest_route_point is not None


# =========================================================================== transitions → alerts (pure)


@pytest.mark.parametrize(
    ("prev", "new", "action"),
    [
        (RouteStatus.NORMAL, RouteStatus.MAJOR_DEVIATION, "raise"),
        (RouteStatus.MINOR_DEVIATION, RouteStatus.MAJOR_DEVIATION, "raise"),
        (None, RouteStatus.MAJOR_DEVIATION, "raise"),
        (RouteStatus.MAJOR_DEVIATION, RouteStatus.MAJOR_DEVIATION, None),
        (RouteStatus.MAJOR_DEVIATION, RouteStatus.NORMAL, "resolve"),
        (RouteStatus.MAJOR_DEVIATION, RouteStatus.MINOR_DEVIATION, "resolve"),
        (RouteStatus.MAJOR_DEVIATION, RouteStatus.NO_ACTIVE_TRIP, "resolve"),
        (RouteStatus.NORMAL, RouteStatus.MINOR_DEVIATION, None),
        (RouteStatus.MINOR_DEVIATION, RouteStatus.NORMAL, None),
    ],
)
def test_alert_transitions(prev, new, action):
    assert alert_action(prev, new) == action


# =========================================================================== simulator + pipeline


async def _sim(container):
    from app.main import attach_simulator

    attach_simulator(container)
    await container.simulator.reset()
    await _advance(container, 10 * 60)
    return container.simulator, container.route_anomaly()


async def _status(container, bus="B05"):
    return (await bus_route_status(container.route_anomaly(), bus)).check


async def _alerts(container):
    """The fleet (admin) route-deviation alerts — Feature 11 also notifies students separately."""
    return [
        a
        for a in await container.repos.alerts.recent()
        if a.type.value == "ROUTE_DEVIATION"
        and a.audience.role is not None
        and a.audience.role.value == "admin"
    ]


async def test_normal_simulation_stays_normal(container):
    sim, _ = await _sim(container)
    for _ in range(8):
        await _advance(container, 60)
        for s in await container.repos.bus_states.list():
            chk = await _status(container, s.id)
            assert chk.status in (RouteStatus.NORMAL, RouteStatus.NO_ACTIVE_TRIP), (s.id, chk)
    assert await _alerts(container) == []
    await sim.shutdown()


async def test_normal_minor_major_normal(container):
    sim, _ = await _sim(container)
    assert (await _status(container)).status is RouteStatus.NORMAL
    sim.set_route_deviation("minor", "B05")
    await _advance(container, 30)
    minor = await _status(container)
    assert minor.status is RouteStatus.MINOR_DEVIATION and MINOR < minor.distance_m < MAJOR
    assert await _alerts(container) == []  # minor never alerts
    assert (await container.repos.bus_states.get("B05")).status is not BusStatus.DEVIATED
    sim.set_route_deviation("major", "B05")
    await _advance(container, 30)
    major = await _status(container)
    assert major.status is RouteStatus.MAJOR_DEVIATION and major.distance_m >= MAJOR
    state = await container.repos.bus_states.get("B05")
    assert state.status is BusStatus.DEVIATED and state.route_status is RouteStatus.MAJOR_DEVIATION
    alerts = await _alerts(container)
    assert len(alerts) == 1 and alerts[0].resolved_at is None  # MINOR → MAJOR: one alert
    assert alerts[0].payload["bus_id"] == "B05" and alerts[0].payload["kind"] == "route_deviation"
    assert alerts[0].body.startswith("BUS B05 is ") and alerts[0].body.endswith("m off its planned route.")
    # MAJOR → MAJOR for many fixes, and repeated polling: still exactly one alert
    await _advance(container, 120)
    for _ in range(10):
        await bus_route_status(container.route_anomaly(), "B05")
    assert len(await _alerts(container)) == 1
    sim.set_route_deviation("normal", "B05")
    await _advance(container, 30)
    assert (await _status(container)).status is RouteStatus.NORMAL
    (alert,) = await _alerts(container)
    assert alert.resolved_at is not None  # MAJOR → NORMAL resolves it
    dev = await container.repos.deviations.open_for_bus("B05")
    assert dev is None
    await sim.shutdown()


async def test_normal_major_normal_and_a_second_episode(container):
    sim, _ = await _sim(container)
    for _ in range(2):
        sim.set_route_deviation("major", "B05")
        await _advance(container, 30)
        assert (await _status(container)).status is RouteStatus.MAJOR_DEVIATION
        sim.set_route_deviation("normal", "B05")
        await _advance(container, 30)
        assert (await _status(container)).status is RouteStatus.NORMAL
    alerts = await _alerts(container)
    assert len(alerts) == 2 and all(a.resolved_at is not None for a in alerts)
    await sim.shutdown()


async def test_global_mode_and_reset_returns_to_normal(container):
    sim, _ = await _sim(container)
    sim.set_route_deviation("major")
    assert sim.status().route_deviation == {"*": "major"}
    await _advance(container, 30)
    statuses = {(await _status(container, s.id)).status for s in await container.repos.bus_states.list()}
    assert RouteStatus.MAJOR_DEVIATION in statuses and RouteStatus.NORMAL not in statuses
    await sim.reset()
    assert sim.status().route_deviation == {}
    await _advance(container, 30)
    statuses = {(await _status(container, s.id)).status for s in await container.repos.bus_states.list()}
    assert statuses <= {RouteStatus.NORMAL, RouteStatus.NO_ACTIVE_TRIP}
    await sim.shutdown()


async def test_simulator_control_validation(container):
    sim, _ = await _sim(container)
    with pytest.raises(ValueError):
        sim.set_route_deviation("sideways")
    with pytest.raises(KeyError):
        sim.set_route_deviation("major", "B99")
    sim.set_route_deviation("minor", "B05")
    sim.set_route_deviation("major", "B06")
    assert sim.status().route_deviation == {"B05": "minor", "B06": "major"}
    sim.set_route_deviation("normal", "B05")
    assert sim.status().route_deviation == {"B06": "major"}
    sim.set_route_deviation("normal")
    assert sim.status().route_deviation == {}
    await sim.shutdown()


async def test_route_geometry_is_never_modified(container):
    sim, _ = await _sim(container)
    before = (await container.repos.routes.get("R3")).path.coordinates
    sim.set_route_deviation("major")
    await _advance(container, 60)
    assert (await container.repos.routes.get("R3")).path.coordinates == before
    await sim.shutdown()


async def test_deviation_interacts_with_features_7_and_9_through_existing_status(container):
    sim, _ = await _sim(container)
    from app.services.bus_comparison_service import BusComparisonService
    from app.services.eta_service import EtaService
    from app.services.matching import MatchingService

    m = MatchingService(container.repos, container.settings)
    eta = EtaService(container.repos, container.settings, container.clock, m)
    commute = CommuteDecisionService(
        BusComparisonService(eta, container.settings, container.clock),
        container.repos,
        container.settings,
        container.clock,
        StudentLocationSource(container.settings),
    )
    assert (await commute.for_student("U-S0001")).result.decision == "YES"  # B05, 07:25
    sim.set_route_deviation("minor", "B05")
    await _advance(container, 30)
    assert (await commute.for_student("U-S0001")).result.decision == "YES"  # minor: informational
    sim.set_route_deviation("major", "B05")
    await _advance(container, 30)
    r = await commute.for_student("U-S0001")
    # existing Feature 7 rule: an off-route bus is never a confident YES — but NOT missed
    assert r.result.decision == "RISK" and r.result.reason.startswith("Your bus is off its usual route")
    await sim.shutdown()


async def test_trip_change_closes_an_open_deviation(container):
    sim, anomaly = await _sim(container)
    sim.set_route_deviation("major", "B05")
    await _advance(container, 30)
    prev = await container.repos.bus_states.get("B05")
    nxt = prev.model_copy(update={"trip_id": "T-NEXT", "ts": prev.ts + timedelta(seconds=5)})
    route = await container.repos.routes.get("R3")
    await anomaly.apply(prev, nxt, route)
    devs = {d.trip_id: d for d in await container.repos.deviations.list()}
    assert devs[prev.trip_id].status.value == "resolved"  # the old trip's deviation is closed
    assert devs["T-NEXT"].status.value == "open"  # still off route on the new trip → new episode
    assert len(await _alerts(container)) == 2
    await sim.shutdown()
