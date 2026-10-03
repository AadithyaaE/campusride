"""Backend ETA: pure prediction rules (real seeded routes) + service over simulator state."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import DEFAULT_TZ
from app.core.errors import ConflictError, NotFoundError
from app.models import BusState, GeoPoint
from app.models.common import BusStatus, Direction, SegmentClass
from app.seed import SeedBundle
from app.services.eta_service import (
    DirectionClassTable,
    EtaPrediction,
    EtaService,
    predict,
    traffic_level,
)
from app.services.matching import MatchingService, ServingBus, locate, match_stop

RADIUS = 40.0
MIDDAY = datetime(2026, 10, 5, 12, 0, tzinfo=DEFAULT_TZ).astimezone(UTC)
PEAK = datetime(2026, 10, 5, 8, 0, tzinfo=DEFAULT_TZ).astimezone(UTC)
NIGHT = datetime(2026, 10, 5, 2, 0, tzinfo=DEFAULT_TZ).astimezone(UTC)


def make_state(
    variant: str, d: float, *, status=BusStatus.EN_ROUTE, speed=8.0, delay_s=0, ts=MIDDAY, bus="B03"
):
    return BusState(
        id=bus,
        trip_id=f"T-{variant}",
        route_id=variant.removesuffix("-E"),
        variant_id=variant,
        direction=Direction.FROM_CAMPUS if variant.endswith("-E") else Direction.TO_CAMPUS,
        ts=ts,
        last_seen=ts,
        location=GeoPoint.of(80.2, 12.9),
        distance_along_m=d,
        speed_mps=speed,
        delay_s=delay_s,
        status=status,
    )


def serving(bundle: SeedBundle, state: BusState, stop_id: str) -> ServingBus:
    route = bundle.route(state.route_id)
    direction = route.variant(state.variant_id)
    bus = next(b for b in bundle.buses if b.id == state.id)
    m = match_stop(state, direction, stop_id, radius_m=RADIUS, approaching_m=1000.0)
    return ServingBus(bus=bus, state=state, route=route, position=locate(state, direction, RADIUS), match=m)


def run(bundle, state, stop_id, *, now=MIDDAY, start=None, stale=False, profiles=None) -> EtaPrediction:
    sb = serving(bundle, state, stop_id)
    return predict(
        sb,
        now=now,
        tz=DEFAULT_TZ,
        profiles=profiles or {SegmentClass(p.id): p for p in bundle.traffic_profiles},
        table=DirectionClassTable(sb.route, sb.position.direction),
        radius_m=RADIUS,
        scheduled_start=start,
        stale=stale,
    )


def stop_d(bundle, variant, stop_id) -> float:
    return bundle.route(variant.removesuffix("-E")).variant(variant).stop(stop_id).distance_along_m


# =========================================================================== baseline


def test_basic_eta_is_finite_positive_and_structured(bundle):
    p = run(bundle, make_state("R2", 1_000), "S08")
    assert p.status == "predicted" and 0 < p.eta_s < 3600
    assert p.estimated_arrival == p.computed_at + timedelta(seconds=p.eta_s)
    assert p.history_source == "timetable" and p.timetable_s > 0
    assert p.eta_minutes == math.ceil(p.eta_s / 60)


def test_baseline_distance_over_effective_speed(bundle):
    """With no current-speed blend (bus dwelling), travel = D / v_model (traffic model speed)."""
    d0 = stop_d(bundle, "R2", "S10")  # dwelling at Velachery Check Post
    sb = serving(bundle, make_state("R2", d0, status=BusStatus.DWELLING, speed=0), "S08")
    p = run(bundle, make_state("R2", d0, status=BusStatus.DWELLING, speed=0), "S08")
    D = sb.match.distance_to_stop_m
    v = D / p.travel_s
    assert 2.5 <= v <= 22.0  # bounded effective speed, derived from the traffic model


@pytest.mark.parametrize("speed", [0.0, 0.01, 0.4])
def test_zero_or_near_zero_speed_is_bounded(bundle, speed):
    p = run(bundle, make_state("R2", 1_000, speed=speed), "S08")
    assert math.isfinite(p.eta_s) and p.eta_s < 3600  # no division by zero, no fake huge ETA


def test_current_speed_influences_eta_when_moving(bundle):
    slow = run(bundle, make_state("R2", 1_000, speed=3.0), "S08")
    fast = run(bundle, make_state("R2", 1_000, speed=15.0), "S08")
    assert fast.eta_s < slow.eta_s


# =========================================================================== factors


def test_traffic_and_time_of_day(bundle):
    peak = run(bundle, make_state("R2", 1_000, ts=PEAK), "S08", now=PEAK)
    noon = run(bundle, make_state("R2", 1_000), "S08", now=MIDDAY)
    night = run(bundle, make_state("R2", 1_000, ts=NIGHT), "S08", now=NIGHT)
    assert peak.traffic_factor > noon.traffic_factor > night.traffic_factor >= 1.0
    assert peak.eta_s > noon.eta_s > night.eta_s
    assert night.traffic_level == "Low" and peak.traffic_level in ("Moderate", "High")


@pytest.mark.parametrize(
    ("factor", "level"), [(1.0, "Low"), (1.15, "Low"), (1.3, "Moderate"), (1.5, "Moderate"), (1.8, "High")]
)
def test_traffic_level_thresholds(factor, level):
    assert traffic_level(factor) == level


def test_historical_timetable_effect_and_fallback(bundle):
    with_history = run(bundle, make_state("R2", 1_000), "S08")
    # Same route without a timetable (all scheduled offsets 0) → model-only, lower confidence.
    route = bundle.route("R2")
    no_tt = route.model_copy(deep=True)
    for d in no_tt.directions:
        for s in d.stops:
            s.scheduled_offset_s = 0
    state = make_state("R2", 1_000)
    direction = no_tt.variant("R2")
    bus = next(b for b in bundle.buses if b.id == "B03")
    sb = ServingBus(
        bus,
        state,
        no_tt,
        locate(state, direction, RADIUS),
        match_stop(state, direction, "S08", radius_m=RADIUS, approaching_m=1000),
    )
    without = predict(
        sb,
        now=MIDDAY,
        tz=DEFAULT_TZ,
        profiles={SegmentClass(p.id): p for p in bundle.traffic_profiles},
        table=DirectionClassTable(no_tt, direction),
        radius_m=RADIUS,
    )
    assert without.history_source is None and without.timetable_s is None
    assert without.eta_s == pytest.approx(without.travel_s + without.dwell_s, abs=0.2)
    assert with_history.eta_s != without.eta_s
    # moving + timetable + traffic → high; losing the timetable drops it to medium
    assert (with_history.confidence, without.confidence) == ("high", "medium")


def test_delay_rescales_pace_without_double_counting(bundle):
    d = stop_d(bundle, "R2", "S12")
    on_time = run(bundle, make_state("R2", d + 200, delay_s=0), "S08")
    late = run(bundle, make_state("R2", d + 200, delay_s=600), "S08")
    early = run(bundle, make_state("R2", d + 200, delay_s=-300), "S08")
    assert late.delay_factor > 1.0 > early.delay_factor
    assert late.eta_s > on_time.eta_s > early.eta_s
    # never "+ delay minutes": the difference is far smaller than the 10-minute delay itself
    assert late.eta_s - on_time.eta_s < 600
    capped = run(bundle, make_state("R2", d + 200, delay_s=100_000), "S08")
    assert capped.delay_factor == 1.5


def test_dwell_at_intermediate_stops_and_current_stop(bundle):
    direction = bundle.route("R2").variant("R2")
    d0 = 100.0
    p = run(bundle, make_state("R2", d0), "S08")
    expected = sum(
        s.dwell_s
        for s in direction.stops
        if d0 + RADIUS < s.distance_along_m < stop_d(bundle, "R2", "S08") - RADIUS
    )
    assert p.dwell_s == pytest.approx(expected)
    near = run(bundle, make_state("R2", d0), "S10")  # no stops in between
    assert near.dwell_s == 0
    s10 = direction.stop("S10")
    dwelling = run(bundle, make_state("R2", s10.distance_along_m, status=BusStatus.DWELLING, speed=0), "S12")
    assert dwelling.dwell_s == pytest.approx(0.5 * s10.dwell_s + direction.stop("S11").dwell_s)


def test_more_remaining_stops_take_longer(bundle):
    etas = [
        run(bundle, make_state("R2", 100), sid).eta_s for sid in ("S10", "S11", "S12", "S13", "S14", "S08")
    ]
    assert etas == sorted(etas)


# =========================================================================== confidence


def test_confidence_levels(bundle):
    d = stop_d(bundle, "R2", "S12")
    high = run(bundle, make_state("R2", d - 800), "S12")  # moving, near, timetable, traffic
    assert high.confidence == "high"
    medium = run(bundle, make_state("R2", 0, speed=0), "S08")  # not moving, far
    assert medium.confidence == "medium"
    low = run(bundle, make_state("R2", 0, speed=0), "S08", stale=True)
    assert low.confidence == "low"
    waiting = run(
        bundle,
        make_state("R2", 0, status=BusStatus.AT_DEPOT, speed=0),
        "S08",
        start=MIDDAY + timedelta(minutes=10),
    )
    assert waiting.confidence in ("low", "medium") and waiting.wait_s == 600


def test_deterministic(bundle):
    a = run(bundle, make_state("R2", 1_234.5, speed=6.6, delay_s=120), "S08")
    b = run(bundle, make_state("R2", 1_234.5, speed=6.6, delay_s=120), "S08")
    assert a == b


# =========================================================================== stop positions & states


def test_first_stop(bundle):
    at_first = run(bundle, make_state("R2", 0, status=BusStatus.AT_DEPOT, speed=0), "S09")
    assert (at_first.status, at_first.eta_s, at_first.eta_minutes) == ("at_stop", 0.0, 0)
    later = run(
        bundle,
        make_state("R2", 0, status=BusStatus.AT_DEPOT, speed=0),
        "S10",
        start=MIDDAY + timedelta(minutes=5),
    )
    now_dep = run(bundle, make_state("R2", 0, status=BusStatus.AT_DEPOT, speed=0), "S10", start=MIDDAY)
    assert later.wait_s == 300 and later.eta_s == pytest.approx(now_dep.eta_s + 300, abs=60)


def test_middle_and_final_stop(bundle):
    middle = run(bundle, make_state("R2", 500), "S12")
    final = run(bundle, make_state("R2", 500), "S00")
    assert middle.status == final.status == "predicted" and final.eta_s > middle.eta_s


def test_passed_and_completed(bundle):
    passed = run(bundle, make_state("R2", stop_d(bundle, "R2", "S12") + 500), "S12")
    assert (passed.status, passed.eta_s, passed.eta_minutes) == ("passed", None, None)
    end = stop_d(bundle, "R2", "S00")
    completed = run(bundle, make_state("R2", end, status=BusStatus.COMPLETED, speed=0), "S12")
    assert completed.status == "completed" and completed.eta_s is None
    arrived = run(bundle, make_state("R2", end, status=BusStatus.COMPLETED, speed=0), "S00")
    assert arrived.status == "at_stop" and arrived.eta_minutes == 0


def test_unrelated_route_cannot_be_predicted(bundle):
    with pytest.raises(ValueError):
        run(bundle, make_state("R2", 500), "S20")  # Tidel Park is not on R2


@pytest.mark.parametrize(
    ("secs", "minutes"), [(0, 0), (30, 0), (59.9, 0), (60, 1), (61, 2), (359.5, 6), (360, 6)]
)
def test_eta_minutes_rounding(secs, minutes):
    p = EtaPrediction("predicted", MIDDAY, secs, "high", "Low", 1.0, 1.0)
    assert p.eta_minutes == minutes and isinstance(p.eta_minutes, int)


# =========================================================================== service (simulator state)


async def _service(container):
    from app.main import attach_simulator

    attach_simulator(container)
    await container.simulator.reset()
    m = MatchingService(container.repos, container.settings)
    return EtaService(container.repos, container.settings, container.clock, m)


async def test_service_orders_multiple_buses_by_eta(container):
    eta = await _service(container)
    items = await eta.stop_arrivals("S08")
    assert {sb.state.variant_id for sb, _ in items} == {"R1", "R2", "R5"}
    secs = [p.eta_s for _, p in items if p.status == "predicted"]
    assert secs == sorted(secs)
    await container.simulator.shutdown()


async def test_service_errors_and_between_trips(container):
    eta = await _service(container)
    with pytest.raises(NotFoundError):
        await eta.bus_eta("B99", "S08")
    with pytest.raises(NotFoundError):
        await eta.bus_eta("B01", "S99")
    with pytest.raises(ConflictError):
        await eta.bus_eta("B01", "S20")  # R1 bus, R3/R4 stop
    await container.repos.bus_states.delete("B01")  # not reporting / between trips
    with pytest.raises(ConflictError, match="no live state"):
        await eta.bus_eta("B01", "S08")
    await container.simulator.shutdown()


async def test_student_arrivals_assigned_and_unassigned(container):
    eta = await _service(container)
    r = await eta.student_arrivals("U-S0001")  # B05 · R3 · S27
    assert r.my_bus[0].bus.id == "B05" and r.my_bus[1] is not None
    assert "B05" in {sb.bus.id for sb, _ in r.arrivals}
    assert {sb.position.direction.direction for sb, _ in r.arrivals} == {Direction.TO_CAMPUS}
    assert await eta.student_arrivals("U-S0025") is None
    await container.simulator.shutdown()
