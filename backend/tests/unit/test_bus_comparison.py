"""Multi-bus comparison: pure rules over Feature 4/5 objects + the service over simulator state."""

from __future__ import annotations

import random
from datetime import timedelta

import pytest

from app.models.common import BusStatus, Direction
from app.services.bus_comparison_service import (
    ALTERNATIVE_MAX_EXTRA_COST_MIN,
    BusComparisonService,
    Indicator,
    compare,
    comparison_cost,
    crowding_level,
    delay_minutes,
    occupancy_percentage,
    seats_available,
)
from app.services.eta_service import EtaPrediction, EtaService
from app.services.matching import MatchingService, ServingBus
from tests.unit.test_eta import MIDDAY, make_state, serving

STALE_AFTER = 45.0
F, LC, A, BA = (
    Indicator.FASTEST,
    Indicator.LEAST_CROWDED,
    Indicator.ASSIGNED,
    Indicator.BEST_ALTERNATIVE,
)


def pred(eta_min: float | None, *, status="predicted", confidence="high") -> EtaPrediction:
    return EtaPrediction(
        status=status,
        computed_at=MIDDAY,
        eta_s=None if eta_min is None else eta_min * 60.0,
        confidence=confidence,
        traffic_level="Moderate",
        traffic_factor=1.3,
        delay_factor=1.0,
    )


def bus_at(
    bundle,
    bus_id: str,
    *,
    d: float = 1_000.0,
    occupancy: int = 10,
    capacity: int | None = None,
    delay_s: int = 0,
    status=BusStatus.EN_ROUTE,
    age_s: float = 0.0,
) -> ServingBus:
    """A bus on R3 heading to S27 (Sholinganallur Junction) — real seeded geometry."""
    s = make_state("R3", d, bus=bus_id, delay_s=delay_s, status=status).model_copy(
        update={"occupancy": occupancy, "last_seen": MIDDAY - timedelta(seconds=age_s)}
    )
    sb = serving(bundle, s, "S27")
    if capacity is not None:
        sb = ServingBus(
            bus=sb.bus.model_copy(update={"capacity": capacity}),
            state=sb.state,
            route=sb.route,
            position=sb.position,
            match=sb.match,
        )
    return sb


def run(items, assigned="B05"):
    return compare(items, assigned_bus_id=assigned, now=MIDDAY, stale_after_s=STALE_AFTER)


def ind(result, bus_id):
    return next(o for o in result.options if o.bus_id == bus_id).indicators


# =========================================================================== occupancy / crowding


@pytest.mark.parametrize(
    ("occ", "cap", "pct"), [(0, 50, 0.0), (46, 50, 92.0), (24, 50, 48.0), (55, 50, 110.0), (-3, 40, 0.0)]
)
def test_occupancy_percentage(occ, cap, pct):
    assert occupancy_percentage(occ, cap) == pytest.approx(pct)


def test_zero_capacity_is_unknown_not_a_crash():
    assert occupancy_percentage(10, 0) is None
    assert crowding_level(None) == "Unknown"
    assert seats_available(10, 0) == 0


@pytest.mark.parametrize(
    ("pct", "band"),
    [(0, "Low"), (59.9, "Low"), (60, "Medium"), (79.9, "Medium"), (80, "High"), (100, "High"), (130, "High")],
)
def test_crowding_bands(pct, band):
    assert crowding_level(pct) == band


def test_seats_and_delay_display_values():
    assert seats_available(46, 50) == 4 and seats_available(60, 50) == 0
    assert delay_minutes(125) == 2 and delay_minutes(-61) == -1 and delay_minutes(0) == 0


# =========================================================================== cost


def test_cost_components_are_documented_weights():
    base = comparison_cost(eta_s=600, pct=40, delay_s=0, confidence="high", assigned=False)
    assert base == pytest.approx(10.0)  # 10 min, nothing else
    assert comparison_cost(eta_s=600, pct=92, delay_s=0, confidence="high", assigned=False) == pytest.approx(
        10 + 0.2 * 42
    )
    assert comparison_cost(eta_s=600, pct=100, delay_s=0, confidence="high", assigned=False) > 40  # full
    assert comparison_cost(eta_s=600, pct=None, delay_s=0, confidence="high", assigned=False) == 15
    assert comparison_cost(eta_s=600, pct=40, delay_s=240, confidence="high", assigned=False) == 11
    assert comparison_cost(eta_s=600, pct=40, delay_s=-240, confidence="high", assigned=False) == 10
    assert comparison_cost(eta_s=600, pct=40, delay_s=0, confidence="low", assigned=False) == 13
    assert comparison_cost(eta_s=600, pct=40, delay_s=0, confidence="high", assigned=True) == 8


def test_comparison_is_deterministic_and_order_independent(bundle):
    items = [
        (bus_at(bundle, "B05", occupancy=46), pred(5)),
        (bus_at(bundle, "B06", occupancy=24, capacity=50), pred(8)),
        (bus_at(bundle, "B11", occupancy=31), pred(11)),
        (bus_at(bundle, "B12", occupancy=40), pred(20)),
    ]
    first = run(items)
    for seed in range(5):
        shuffled = items[:]
        random.Random(seed).shuffle(shuffled)
        again = run(shuffled)
        assert {o.bus_id: (o.indicators, o.cost) for o in again.options} == {
            o.bus_id: (o.indicators, o.cost) for o in first.options
        }


# =========================================================================== indicators


def test_spec_trade_off_example(bundle):
    """Assigned bus is fastest but crowded; a later emptier bus is the best alternative."""
    r = run(
        [
            (bus_at(bundle, "B05", occupancy=46), pred(5)),  # assigned, 92 %
            (bus_at(bundle, "B06", occupancy=24, capacity=50), pred(8)),  # 48 %
            (bus_at(bundle, "B11", occupancy=31), pred(11)),  # 62 %
        ]
    )
    assert ind(r, "B05") == (A, F)
    assert ind(r, "B06") == (LC, BA)
    assert ind(r, "B11") == ()
    b06 = next(o for o in r.options if o.bus_id == "B06")
    assert (b06.occupancy_percentage, b06.crowding, b06.seats_available) == (48, "Low", 26)
    assert b06.trade_off == "+3 min vs B05 · 22 more seats free"
    assert next(o for o in r.options if o.bus_id == "B05").trade_off is None  # the reference bus


def test_best_alternative_is_not_simply_second_fastest(bundle):
    r = run(
        [
            (bus_at(bundle, "B05", occupancy=20), pred(4)),
            (bus_at(bundle, "B06", occupancy=38, capacity=40), pred(6)),  # 2nd fastest, 95 % full
            (bus_at(bundle, "B11", occupancy=15), pred(9)),  # later, plenty of room
        ]
    )
    assert BA in ind(r, "B11") and BA not in ind(r, "B06")


def test_best_alternative_considers_delay_and_confidence(bundle):
    r = run(
        [
            (bus_at(bundle, "B05", occupancy=10), pred(4)),
            (bus_at(bundle, "B06", occupancy=10, capacity=50, delay_s=20 * 60), pred(9)),  # late
            (bus_at(bundle, "B11", occupancy=10), pred(10)),
        ]
    )
    assert BA in ind(r, "B11")  # 9 + 5 (delay risk) > 10
    r = run(
        [
            (bus_at(bundle, "B05", occupancy=10), pred(4)),
            (bus_at(bundle, "B06", occupancy=10, capacity=50), pred(9, confidence="low")),
            (bus_at(bundle, "B11", occupancy=10), pred(10)),
        ]
    )
    assert BA in ind(r, "B11")  # 9 + 3 (low confidence) > 10


def test_full_bus_is_never_best_alternative(bundle):
    r = run(
        [
            (bus_at(bundle, "B05", occupancy=10), pred(3)),
            (bus_at(bundle, "B06", occupancy=40, capacity=40), pred(5)),  # full
        ]
    )
    assert ind(r, "B06") == ()


def test_no_alternative_when_far_worse_than_fastest(bundle):
    r = run(
        [
            (bus_at(bundle, "B05", occupancy=10), pred(3)),
            (bus_at(bundle, "B11", occupancy=10), pred(3 + ALTERNATIVE_MAX_EXTRA_COST_MIN + 4)),
        ],
        assigned="B05",
    )
    assert r.with_indicator(BA) is None
    assert ind(r, "B11") == ()  # B05 is both fastest and least crowded (tie → sooner)


def test_assigned_bus_can_be_fastest_and_least_crowded(bundle):
    r = run(
        [
            (bus_at(bundle, "B05", occupancy=5), pred(3)),
            (bus_at(bundle, "B11", occupancy=30), pred(6)),
        ]
    )
    assert ind(r, "B05") == (A, F, LC)  # multiple indicators on one bus
    assert ind(r, "B11") == (BA,)


def test_assigned_bus_can_be_best_alternative(bundle):
    r = run(
        [
            (bus_at(bundle, "B11", occupancy=48), pred(2)),  # fastest, 96 %
            (bus_at(bundle, "B05", occupancy=20), pred(6)),  # assigned
            (bus_at(bundle, "B12", occupancy=5), pred(7)),
        ]
    )
    assert ind(r, "B11") == (F,)
    assert ind(r, "B05") == (A, BA)
    assert ind(r, "B12") == (LC,)


def test_assigned_only_marks_the_college_assigned_bus(bundle):
    r = run([(bus_at(bundle, "B05"), pred(3)), (bus_at(bundle, "B11"), pred(5))], assigned="B11")
    assert [o.bus_id for o in r.options if o.assigned] == ["B11"]
    assert A in ind(r, "B11") and A not in ind(r, "B05")


def test_least_crowded_uses_percentage_not_headcount(bundle):
    r = run(
        [
            (bus_at(bundle, "B06", occupancy=20, capacity=40), pred(4)),  # 50 %
            (bus_at(bundle, "B11", occupancy=22), pred(6)),  # 44 % of 50
        ],
        assigned=None,
    )
    assert LC in ind(r, "B11")


def test_zero_capacity_bus_is_compared_but_never_least_crowded(bundle):
    r = run(
        [
            (bus_at(bundle, "B05", occupancy=0, capacity=0), pred(3)),
            (bus_at(bundle, "B11", occupancy=30), pred(5)),
        ]
    )
    zero = next(o for o in r.options if o.bus_id == "B05")
    assert (zero.occupancy_percentage, zero.crowding, zero.comparable) == (None, "Unknown", True)
    assert LC in ind(r, "B11") and LC not in ind(r, "B05")


# =========================================================================== which buses are options


def test_passed_and_completed_buses_are_excluded(bundle):
    r = run(
        [
            (bus_at(bundle, "B05"), pred(4)),
            (bus_at(bundle, "B06", d=20_000), pred(None, status="passed")),
            (bus_at(bundle, "B11", status=BusStatus.COMPLETED), pred(None, status="completed")),
            (bus_at(bundle, "B12"), pred(9)),
        ]
    )
    assert [o.bus_id for o in r.options] == ["B05", "B12"]
    assert [(x.sb.bus.id, x.reason) for x in r.excluded] == [
        ("B06", "passed_stop"),
        ("B11", "trip_completed"),
    ]


def test_bus_dwelling_at_the_stop_is_an_option(bundle):
    r = run([(bus_at(bundle, "B11"), pred(0, status="at_stop")), (bus_at(bundle, "B05"), pred(4))])
    assert F in ind(r, "B11") and next(o for o in r.options if o.bus_id == "B11").prediction.eta_minutes == 0


def test_stale_and_broken_down_buses_are_listed_without_indicators(bundle):
    r = run(
        [
            (bus_at(bundle, "B11", occupancy=1, age_s=STALE_AFTER + 30), pred(1)),  # stale
            (bus_at(bundle, "B12", occupancy=1, status=BusStatus.BREAKDOWN), pred(2)),
            (bus_at(bundle, "B05", occupancy=30), pred(4)),
            (bus_at(bundle, "B06", occupancy=30, capacity=50), pred(6)),
        ]
    )
    stale = next(o for o in r.options if o.bus_id == "B11")
    assert stale.stale and not stale.comparable and stale.cost is None and stale.indicators == ()
    assert ind(r, "B12") == ()
    assert ind(r, "B05") == (A, F, LC)  # fastest/least crowded among LIVE buses


def test_single_bus_or_none_has_nothing_to_compare(bundle):
    r = run([(bus_at(bundle, "B05", occupancy=5), pred(3))])
    assert ind(r, "B05") == (A,)  # no FASTEST / LEAST_CROWDED / BEST_ALTERNATIVE of one
    r = run([(bus_at(bundle, "B11", occupancy=5), pred(3))])
    assert ind(r, "B11") == ()
    assert run([]).options == [] and run([]).excluded == []


def test_options_keep_feature5_arrival_order(bundle):
    items = [
        (bus_at(bundle, "B05", occupancy=46), pred(5)),
        (bus_at(bundle, "B06", occupancy=24, capacity=50), pred(8)),
        (bus_at(bundle, "B11", occupancy=31), pred(11)),
    ]
    assert [o.bus_id for o in run(items).options] == ["B05", "B06", "B11"]


def test_trade_off_wording(bundle):
    r = run(
        [
            (bus_at(bundle, "B05", occupancy=20), pred(4)),
            (bus_at(bundle, "B11", occupancy=21), pred(4)),
            (bus_at(bundle, "B12", occupancy=10), pred(9)),
        ]
    )
    by = {o.bus_id: o.trade_off for o in r.options}
    assert by == {
        "B05": None,
        "B11": "Same time as B05 · 1 fewer seat free",
        "B12": "+5 min vs B05 · 10 more seats free",
    }


# =========================================================================== service (simulator state)


async def _service(container) -> BusComparisonService:
    from app.main import attach_simulator

    attach_simulator(container)
    await container.simulator.reset()
    eta = EtaService(
        container.repos,
        container.settings,
        container.clock,
        MatchingService(container.repos, container.settings),
    )
    return BusComparisonService(eta, container.settings, container.clock)


async def _advance(container, seconds):
    for _ in range(seconds // 5):
        container.clock.advance(5)
        await container.simulator.step_until(container.clock.now())


async def test_service_uses_assignment_stop_direction_and_feature5_eta(container):
    svc = await _service(container)
    await _advance(container, 24 * 60)
    r = await svc.for_student("U-S0001")  # B05 · R3 · S27 Sholinganallur Junction
    assert r.assignment.bus.id == "B05" and r.assignment.boarding_stop.id == "S27"
    assert len(r.comparison.options) >= 3
    for o in r.comparison.options:
        d = o.sb.position.direction
        assert d.direction is Direction.TO_CAMPUS and d.stop("S27") is not None  # same stop + direction
        assert o.sb.match is not None and o.sb.match.stop.stop_id == "S27"
        assert o.sb.route.id != "R1"  # R1 never serves S27 → unrelated route filtered by matching
        assert o.delay_minutes == round(o.sb.state.delay_s / 60)  # delay from tracked state
    # ETA integration: identical to Feature 5 for the same bus at the same instant
    arrivals = await svc._eta.student_arrivals("U-S0001")
    f5 = {sb.bus.id: p.eta_s for sb, p in arrivals.arrivals}
    assert {o.bus_id: o.prediction.eta_s for o in r.comparison.options} == {
        k: v for k, v in f5.items() if k in {o.bus_id for o in r.comparison.options}
    }
    assert r.assigned_option is not None and A in r.assigned_option.indicators
    assert r.comparison.with_indicator(F) is not None
    await container.simulator.shutdown()


async def test_service_passed_completed_and_between_trips(container):
    svc = await _service(container)
    await _advance(container, 42 * 60)
    r = await svc.for_student("U-S0001")
    ids = {o.bus_id for o in r.comparison.options}
    assert "B05" not in ids and r.assigned_option is None  # assigned bus already gone by
    gone = {x.sb.bus.id: x.reason for x in r.comparison.excluded}
    assert gone.get("B05") in ("passed_stop", "trip_completed")
    assert all(o.prediction.status in ("predicted", "at_stop") for o in r.comparison.options)
    await container.repos.bus_states.delete("B05")  # not reporting / between trips
    r = await svc.for_student("U-S0001")
    assert r.my_bus is None and "B05" not in {x.sb.bus.id for x in r.comparison.excluded}
    await container.simulator.shutdown()


async def test_service_unassigned_student(container):
    svc = await _service(container)
    assert await svc.for_student("U-S0025") is None
    await container.simulator.shutdown()
