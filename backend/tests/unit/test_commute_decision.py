"""Commute decision: pure rules + the service over simulator state (Feature 7)."""

from __future__ import annotations

import math
from datetime import timedelta

import pytest

from app.core.config import Settings
from app.models.common import BusStatus
from app.services.commute_decision_service import (
    REASON,
    AssignedBus,
    CommuteDecisionService,
    evaluate_commute,
    walking_time_s,
)
from app.services.student_location import SYNTHETIC_MAX_M, SYNTHETIC_MIN_M, StudentLocationSource
from tests.unit.test_bus_comparison import _advance, _service, pred
from tests.unit.test_eta import MIDDAY

NOW = MIDDAY
BUFFER = 120.0
SPEED = 1.4


def bus(
    eta_min: float | None = 10, *, status=BusStatus.EN_ROUTE, eta_status="predicted", stale=False, delay_s=0
):
    p = None if eta_status is None else pred(eta_min, status=eta_status)
    return AssignedBus(status=status, prediction=p, stale=stale, delay_s=delay_s)


def walk_m(minutes: float) -> float:
    return minutes * 60 * SPEED


def decide(b, walk_minutes: float | None = 4, *, speed=SPEED, buffer=BUFFER):
    return evaluate_commute(
        now=NOW,
        bus=b,
        walking_distance_m=None if walk_minutes is None else walk_m(walk_minutes),
        walking_speed_mps=speed,
        safety_buffer_s=buffer,
    )


# =========================================================================== walking


def test_walking_time():
    assert walking_time_s(700, 1.4) == pytest.approx(500)
    assert walking_time_s(0, 1.4) == 0
    for bad in (0, -1.0, math.nan, math.inf):
        assert walking_time_s(500, bad) is None


def test_zero_walking_distance_student_at_the_stop():
    r = decide(bus(3), walk_minutes=0)
    assert r.decision == "YES" and r.walking_time_minutes == 0  # "<1 min"
    assert r.walking_distance_m == 0


@pytest.mark.parametrize("speed", [0.0, -1.4, math.nan])
def test_invalid_walking_speed_is_unknown_not_a_crash(speed):
    r = decide(bus(10), speed=speed)
    assert r.decision == "UNKNOWN" and r.reason == REASON["bad_speed"]
    assert r.walking_time_s is None


def test_walking_minutes_are_whole_and_rounded_up():
    assert decide(bus(30), walk_minutes=3.2).walking_time_minutes == 4
    assert decide(bus(30), walk_minutes=4).walking_time_minutes == 4
    assert decide(bus(30), walk_minutes=0.5).walking_time_minutes == 0


# =========================================================================== YES / RISK boundary


def test_yes():
    r = decide(bus(8), walk_minutes=4)
    assert r.decision == "YES" and r.reason == "You should reach your stop before the bus."
    assert (r.walking_time_minutes, r.bus_eta_minutes, r.safety_buffer_s) == (4, 8, 120)
    assert r.required_arrival_time == r.bus_arrival_time - timedelta(minutes=2)
    assert r.student_arrival_time == NOW + timedelta(minutes=4)
    assert r.spare_s == pytest.approx(240)


def test_risk_when_walk_fits_eta_but_not_the_buffer():
    r = decide(bus(5), walk_minutes=4)
    assert r.decision == "RISK"
    assert r.reason == "You may reach the stop, but there is little time to spare."


def test_walk_plus_buffer_just_under_eta_is_yes():
    assert decide(bus(8), walk_minutes=5.99).decision == "YES"  # 5.99 + 2 < 8


def test_exact_equality_at_the_safety_buffer_boundary_is_risk():
    # walking_time + safety_buffer == bus_eta → RISK (documented boundary)
    r = decide(bus(8), walk_minutes=6)
    assert r.student_arrival_time == r.required_arrival_time
    assert r.decision == "RISK"


def test_walking_longer_than_eta_is_risk_not_missed():
    r = decide(bus(3), walk_minutes=7)
    assert r.decision == "RISK" and r.reason == REASON["late"]
    assert r.spare_s == pytest.approx(-240)


def test_safety_buffer_is_configurable():
    assert decide(bus(8), walk_minutes=6, buffer=0).decision == "YES"
    assert decide(bus(8), walk_minutes=6, buffer=-30).decision == "YES"  # negative → 0
    assert decide(bus(8), walk_minutes=3, buffer=300).decision == "RISK"


def test_student_far_away():
    r = decide(bus(15), walk_minutes=40)
    assert r.decision == "RISK" and r.reason == REASON["late"]


# =========================================================================== bus states


def test_bus_at_the_stop():
    r = decide(bus(0, eta_status="at_stop", status=BusStatus.DWELLING), walk_minutes=5)
    assert r.decision == "RISK" and r.reason == REASON["at_stop"] and r.bus_eta_minutes == 0
    near = decide(bus(0, eta_status="at_stop", status=BusStatus.DWELLING), walk_minutes=0.5)
    assert near.decision == "RISK" and near.reason == REASON["at_stop_go"]


def test_bus_approaching_and_dwelling_elsewhere_use_timing():
    assert decide(bus(2), walk_minutes=0).decision == "RISK"  # 0 + 2 ≥ 2
    assert decide(bus(3), walk_minutes=0.5).decision == "YES"
    assert decide(bus(9, status=BusStatus.DWELLING), walk_minutes=4).decision == "YES"


def test_passed_bus_is_missed_whatever_the_timing():
    r = decide(bus(None, eta_status="passed"), walk_minutes=0)
    assert r.decision == "MISSED" and r.reason == "Your assigned bus has already passed your stop."
    assert decide(bus(None, eta_status="passed"), walk_minutes=None).decision == "MISSED"


def test_completed_trip_is_missed():
    r = decide(bus(None, eta_status="completed", status=BusStatus.COMPLETED))
    assert r.decision == "MISSED" and r.reason == REASON["completed"]


def test_between_trips_not_serving_the_stop_is_missed():
    r = decide(bus(eta_status=None, status=BusStatus.AT_DEPOT))
    assert r.decision == "MISSED" and r.reason == REASON["not_serving"]


def test_elapsed_arrival_time_is_missed_and_boundary_is_not():
    p = pred(5)
    old = AssignedBus(BusStatus.EN_ROUTE, p, False, 0)
    later = evaluate_commute(
        now=NOW + timedelta(minutes=6),
        bus=old,
        walking_distance_m=10,
        walking_speed_mps=SPEED,
        safety_buffer_s=BUFFER,
    )
    assert later.decision == "MISSED" and later.reason == REASON["elapsed"]
    exactly = evaluate_commute(
        now=NOW + timedelta(minutes=5),
        bus=old,
        walking_distance_m=10,
        walking_speed_mps=SPEED,
        safety_buffer_s=BUFFER,
    )
    assert exactly.decision == "RISK" and exactly.bus_eta_s == 0  # due now, not yet passed


def test_delay_is_not_double_counted():
    on_time = decide(bus(8), walk_minutes=4)
    late = decide(bus(8, delay_s=600), walk_minutes=4)  # ETA (Feature 5) already includes delay
    assert late.decision == on_time.decision == "YES"
    assert late.bus_arrival_time == on_time.bus_arrival_time


def test_delayed_bus_alone_is_never_missed():
    assert decide(bus(1, delay_s=1200), walk_minutes=10).decision == "RISK"


def test_stale_telemetry_never_says_yes():
    r = decide(bus(20, stale=True), walk_minutes=2)
    assert r.decision == "RISK"
    assert r.reason == "Bus location is not updating, so arrival timing is uncertain."
    assert decide(bus(None, eta_status="passed", stale=True)).decision == "MISSED"


def test_breakdown_and_deviation_are_conservative():
    assert decide(bus(20, status=BusStatus.BREAKDOWN), 2).reason == REASON["breakdown"]
    assert decide(bus(20, status=BusStatus.BREAKDOWN), 2).decision == "RISK"
    assert decide(bus(20, status=BusStatus.DEVIATED), 2).decision == "RISK"


def test_missing_location_is_explicit():
    r = decide(bus(10), walk_minutes=None)
    assert r.decision == "LOCATION_UNAVAILABLE" and r.walking_time_s is None
    assert r.bus_eta_minutes == 10  # the bus side is still reported


def test_missing_eta_and_unavailable_bus():
    no_eta = AssignedBus(BusStatus.EN_ROUTE, pred(None, status="predicted"), False, 0)
    assert decide(no_eta).decision == "UNKNOWN" and decide(no_eta).reason == REASON["no_eta"]
    assert decide(None).decision == "UNKNOWN" and decide(None).reason == REASON["no_bus"]


def test_deterministic():
    runs = {decide(bus(7.3), walk_minutes=3.1) for _ in range(5)}
    assert len(runs) == 1


# =========================================================================== synthetic location


def test_synthetic_location_is_deterministic_labelled_and_near_the_stop(bundle):
    from app.geo import haversine_m

    s = Settings(_env_file=None, app_env="test", seed=42, mock_token_secret="x")
    stop = next(x for x in bundle.stops if x.id == "S27")
    src = StudentLocationSource(s)
    a, b = src.locate("U-S0001", stop), src.locate("U-S0001", stop)
    assert a == b and a.source == "synthetic" and "not GPS" in a.label
    d = haversine_m(a.point, tuple(stop.location.coordinates))
    assert SYNTHETIC_MIN_M - 1 <= d <= SYNTHETIC_MAX_M + 1
    assert src.locate("U-S0002", stop) != a
    off = StudentLocationSource(s.model_copy(update={"student_location_mode": "off"}))
    assert off.locate("U-S0001", stop) is None


# =========================================================================== service (simulator state)


async def _commute(container) -> CommuteDecisionService:
    comparison = await _service(container)
    return CommuteDecisionService(
        comparison,
        container.repos,
        container.settings,
        container.clock,
        StudentLocationSource(container.settings),
    )


async def test_service_assigned_bus_yes_then_risk_then_missed(container):
    svc = await _commute(container)
    r = await svc.for_student("U-S0001")  # B05 · S27; synthetic walk ≈ 11 min
    assert r.assignment.bus.id == "B05" and r.result.decision == "YES"
    assert r.location is not None and r.location.source == "synthetic"
    profile = await container.repos.student_profiles.get("U-S0001")
    assert r.result.walking_speed_mps == profile.walk_speed_mps  # the student's own speed
    # the ETA is exactly Feature 5's prediction for the assigned bus
    assert r.prediction is not None and r.result.bus_arrival_time == r.prediction.estimated_arrival
    await _advance(container, 21 * 60)
    assert (await svc.for_student("U-S0001")).result.decision == "RISK"
    await _advance(container, 15 * 60)
    late = await svc.for_student("U-S0001")
    assert late.result.decision == "MISSED"  # B05 passed S27 — overrides timing
    assert late.alternatives_available >= 1  # Feature 6 options exist, but are not chosen
    assert late.assignment.bus.id == "B05"
    await container.simulator.shutdown()


async def test_service_stale_unavailable_and_location_off(container):
    svc = await _commute(container)
    await _advance(container, 3 * 60)
    state = await container.repos.bus_states.get("B05")
    old = state.model_copy(update={"last_seen": state.last_seen - timedelta(minutes=5)})
    await container.repos.bus_states.upsert(old)
    r = await svc.for_student("U-S0001")
    assert r.stale and r.result.decision == "RISK" and r.result.reason == REASON["stale"]
    await container.repos.bus_states.delete("B05")
    r = await svc.for_student("U-S0001")
    assert r.my_bus is None and r.result.decision == "UNKNOWN"
    container.settings = container.settings.model_copy(update={"student_location_mode": "off"})
    svc = CommuteDecisionService(
        svc._comparison,
        container.repos,
        container.settings,
        container.clock,
        StudentLocationSource(container.settings),
    )
    await _advance(container, 5)
    r = await svc.for_student("U-S0001")
    assert r.result.decision == "LOCATION_UNAVAILABLE" and r.location is None
    await container.simulator.shutdown()


async def test_service_unassigned(container):
    svc = await _commute(container)
    assert await svc.for_student("U-S0025") is None
    await container.simulator.shutdown()
