"""Missed-bus recovery (Feature 9): trigger, screening, Feature 7 catch check, ranking, service."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.common import BusStatus, Direction
from app.services.bus_comparison_service import compare
from app.services.commute_decision_service import CommuteDecisionService
from app.services.missed_bus_service import (
    MissedBusService,
    plan_recovery,
    rank_key,
    recovery_trigger,
)
from app.services.student_location import StudentLocationSource
from tests.unit.test_bus_comparison import _advance, _service, bus_at, pred
from tests.unit.test_eta import MIDDAY

NOW = MIDDAY
SPEED = 1.4
BUFFER = 120.0
THRESHOLD = 300.0


def walk_m(minutes: float) -> float:
    return minutes * 60 * SPEED


def commute(
    bundle,
    others,
    *,
    decision="RISK",
    walk_min: float | None = 4,
    speed=SPEED,
    assigned_delay_s=0,
    assigned_serving=True,
):
    """A Feature 7 result whose Feature 6 options are ``others`` + the assigned bus B05."""
    mine = bus_at(bundle, "B05", d=1_000, delay_s=assigned_delay_s)
    mine_pred = pred(3 if assigned_serving else None, status="predicted" if assigned_serving else "passed")
    items = [(mine, mine_pred), *others]
    return SimpleNamespace(
        result=SimpleNamespace(decision=decision),
        prediction=mine_pred if assigned_serving else None,
        my_bus=mine,
        assignment=SimpleNamespace(bus=SimpleNamespace(id="B05")),
        options=SimpleNamespace(
            comparison=compare(items, assigned_bus_id="B05", now=NOW, stale_after_s=45.0)
        ),
        walking_distance_m=None if walk_min is None else walk_m(walk_min),
        walking_speed_mps=speed,
    )


def plan(c, max_alternatives=3):
    return plan_recovery(
        c, now=NOW, delay_threshold_s=THRESHOLD, buffer_s=BUFFER, max_alternatives=max_alternatives
    )


def ids(r):
    return [o.candidate.bus_id for o in ([r.recommended] if r.recommended else []) + r.alternatives]


def excluded(r):
    return {x.bus_id: x.reason for x in r.excluded}


# =========================================================================== triggers


def test_trigger_rules():
    t = recovery_trigger
    assert t("YES", assigned_serving=True, assigned_delay_s=0, threshold_s=300) is None
    assert t("RISK", assigned_serving=True, assigned_delay_s=0, threshold_s=300) == "likely_to_miss"
    assert t("MISSED", assigned_serving=False, assigned_delay_s=0, threshold_s=300) == "missed"
    assert t("YES", assigned_serving=True, assigned_delay_s=300, threshold_s=300) == "significantly_delayed"
    assert t("YES", assigned_serving=True, assigned_delay_s=299, threshold_s=300) is None
    assert t("YES", assigned_serving=False, assigned_delay_s=900, threshold_s=300) is None
    # RISK wins over delay: the more urgent explanation
    assert t("RISK", assigned_serving=True, assigned_delay_s=900, threshold_s=300) == "likely_to_miss"
    assert t("LOCATION_UNAVAILABLE", assigned_serving=True, assigned_delay_s=0, threshold_s=300) is None


def test_no_recovery_when_assigned_bus_is_catchable(bundle):
    r = plan(commute(bundle, [(bus_at(bundle, "B11"), pred(9))], decision="YES"))
    assert r.status == "not_needed" and r.recommended is None and r.alternatives == []


def test_recovery_on_risk_missed_and_delay(bundle):
    others = [(bus_at(bundle, "B11"), pred(9))]
    assert plan(commute(bundle, others, decision="RISK")).trigger == "likely_to_miss"
    missed = plan(commute(bundle, others, decision="MISSED", assigned_serving=False))
    assert missed.status == "recovery_available" and missed.trigger == "missed"
    delayed = plan(commute(bundle, others, decision="YES", assigned_delay_s=420))
    assert delayed.trigger == "significantly_delayed" and ids(delayed) == ["B11"]


def test_no_alternative(bundle):
    r = plan(commute(bundle, [], decision="MISSED", assigned_serving=False))
    assert r.status == "no_alternative" and r.trigger == "missed"
    assert r.recommended is None and r.alternatives == []


# =========================================================================== screening


def test_assigned_bus_is_never_offered(bundle):
    r = plan(commute(bundle, [(bus_at(bundle, "B11"), pred(9))]))
    assert "B05" not in ids(r) and "B05" not in excluded(r)


def test_passed_and_completed_buses_excluded(bundle):
    r = plan(
        commute(
            bundle,
            [
                (bus_at(bundle, "B06", d=20_000), pred(None, status="passed")),
                (bus_at(bundle, "B11", status=BusStatus.COMPLETED), pred(None, status="completed")),
                (bus_at(bundle, "B12"), pred(9)),
            ],
        )
    )
    assert ids(r) == ["B12"]
    assert excluded(r) == {"B06": "passed_stop", "B11": "trip_completed"}


def test_stale_broken_down_off_route_and_at_stop_excluded(bundle):
    r = plan(
        commute(
            bundle,
            [
                (bus_at(bundle, "B06", capacity=50, age_s=120), pred(8)),
                (bus_at(bundle, "B11", status=BusStatus.BREAKDOWN), pred(8)),
                (bus_at(bundle, "B12", status=BusStatus.DEVIATED), pred(8)),
                (bus_at(bundle, "B07"), pred(0, status="at_stop")),
                (bus_at(bundle, "B08"), pred(10)),
            ],
        )
    )
    assert ids(r) == ["B08"]
    assert excluded(r) == {"B06": "stale", "B11": "breakdown", "B12": "off_route", "B07": "at_stop_now"}


def test_full_bus_excluded(bundle):
    r = plan(
        commute(
            bundle,
            [(bus_at(bundle, "B11", occupancy=50), pred(8)), (bus_at(bundle, "B12", occupancy=49), pred(9))],
        )
    )
    assert ids(r) == ["B12"] and excluded(r) == {"B11": "full"}


# ===================================================================== catch feasibility (Feature 7)


def test_catchable_and_not_catchable(bundle):
    r = plan(
        commute(bundle, [(bus_at(bundle, "B11"), pred(5)), (bus_at(bundle, "B12"), pred(12))], walk_min=4)
    )
    # B11: 4 + 2 ≥ 5 → too late (dropped); B12: 4 + 2 < 12 → catchable
    assert ids(r) == ["B12"] and excluded(r) == {"B11": "too_late"}
    rec = r.recommended.candidate
    assert rec.catchable is True and rec.spare_minutes == 8


def test_safety_buffer_boundary_is_strict(bundle):
    # walk 6 + buffer 2 == ETA 8 → NOT catchable (same rule as Feature 7)
    r = plan(commute(bundle, [(bus_at(bundle, "B11"), pred(8))], walk_min=6))
    assert r.status == "no_alternative" and excluded(r) == {"B11": "too_late"}
    assert ids(plan(commute(bundle, [(bus_at(bundle, "B11"), pred(8))], walk_min=5.9))) == ["B11"]


def test_location_unavailable_never_claims_catchable(bundle):
    r = plan(commute(bundle, [(bus_at(bundle, "B11"), pred(5))], walk_min=None))
    rec = r.recommended
    assert rec.candidate.catchable is None and rec.candidate.spare_minutes is None
    assert "can't be confirmed" in rec.reason


def test_invalid_walking_speed_reuses_feature7_behaviour(bundle):
    r = plan(commute(bundle, [(bus_at(bundle, "B11"), pred(9))], speed=0.0))
    assert r.recommended.candidate.catchable is None  # Feature 7: UNKNOWN, never a confident yes
    assert r.recommended.candidate.catch.decision == "UNKNOWN"


# =========================================================================== ranking


def test_eta_ordering(bundle):
    r = plan(
        commute(
            bundle,
            [
                (bus_at(bundle, "B12"), pred(20)),
                (bus_at(bundle, "B11"), pred(9)),
                (bus_at(bundle, "B06", capacity=50), pred(14)),
            ],
        )
    )
    assert ids(r) == ["B11", "B06", "B12"]


def test_occupancy_tie_break(bundle):
    r = plan(
        commute(
            bundle,
            [(bus_at(bundle, "B11", occupancy=30), pred(9)), (bus_at(bundle, "B12", occupancy=10), pred(9))],
        )
    )
    assert ids(r) == ["B12", "B11"]


def test_route_status_tie_break(bundle):
    r = plan(
        commute(
            bundle,
            [
                (bus_at(bundle, "B11", occupancy=10, delay_s=400), pred(9)),  # delayed
                (bus_at(bundle, "B12", occupancy=10), pred(9)),
            ],
        )
    )
    assert ids(r) == ["B12", "B11"]
    assert r.alternatives[0].candidate.delayed  # a delayed alternative is still offered


def test_distance_tie_break(bundle):
    r = plan(
        commute(
            bundle,
            [
                (bus_at(bundle, "B11", d=1_000, occupancy=10), pred(9)),
                (bus_at(bundle, "B12", d=5_000, occupancy=10), pred(9)),  # closer to S27
            ],
        )
    )
    assert ids(r) == ["B12", "B11"]


def test_bus_id_final_tie_break_and_determinism(bundle):
    others = [(bus_at(bundle, b, d=2_000, occupancy=10), pred(9)) for b in ("B12", "B07", "B11")]
    first = ids(plan(commute(bundle, others)))
    assert first == ["B07", "B11", "B12"]
    assert ids(plan(commute(bundle, list(reversed(others))))) == first


def test_catchable_ranks_before_unknown():
    def cand(bus_id, catchable, eta):
        return SimpleNamespace(
            catchable=catchable,
            eta_s=eta,
            option=SimpleNamespace(occupancy_pct=10.0),
            delayed=False,
            distance_m=100.0,
            bus_id=bus_id,
        )

    ordered = sorted([cand("A", None, 60), cand("B", True, 600)], key=rank_key)
    assert [c.bus_id for c in ordered] == ["B", "A"]


def test_maximum_alternatives(bundle):
    others = [
        (bus_at(bundle, b, capacity=50), pred(9 + i))
        for i, b in enumerate(["B06", "B07", "B08", "B11", "B12"])
    ]
    r = plan(commute(bundle, others))
    assert ids(r) == ["B06", "B07", "B08", "B11"] and len(r.alternatives) == 3
    assert len(plan(commute(bundle, others), max_alternatives=1).alternatives) == 1


# =========================================================================== reasons


def test_reason_text_comes_from_actual_values(bundle):
    r = plan(
        commute(
            bundle,
            [
                (bus_at(bundle, "B07", occupancy=40), pred(5)),  # too late with a 4-min walk
                (bus_at(bundle, "B11", occupancy=30), pred(11)),
                (bus_at(bundle, "B12", occupancy=5), pred(15)),
            ],
            walk_min=4,
        )
    )
    assert r.recommended.reason == (
        "Bus B11 is the next catchable bus serving your stop and gives you a 7-minute safety buffer."
    )
    assert r.alternatives[0].reason == (
        "Bus B12 is less crowded and still gives you enough time to reach the stop (11 min to spare)."
    )
    plain = plan(commute(bundle, [(bus_at(bundle, "B11"), pred(12))], walk_min=1))
    assert plain.recommended.reason == "Bus B11 serves your stop and gives you an 11-minute safety buffer."


# =========================================================================== service over the simulator


async def _recovery(container) -> MissedBusService:
    comparison = await _service(container)
    commute_svc = CommuteDecisionService(
        comparison,
        container.repos,
        container.settings,
        container.clock,
        StudentLocationSource(container.settings),
    )
    return MissedBusService(commute_svc, container.settings, container.clock)


def _all_listed(r):
    return ids(r) + list(excluded(r))


async def test_simulator_transitions_yes_risk_missed(container):
    svc = await _recovery(container)
    first = await svc.for_student("U-S0001")  # B05 · R3 · S27; ~11 min walk
    assert first.commute.result.decision == "YES" and first.recovery.status == "not_needed"
    await _advance(container, 20 * 60)
    risk = await svc.for_student("U-S0001")
    assert risk.commute.result.decision == "RISK"  # the decision itself is unchanged
    assert risk.recovery.status == "recovery_available" and risk.recovery.trigger == "likely_to_miss"
    assert risk.recovery.recommended.candidate.catchable is True
    await _advance(container, 16 * 60)
    missed = await svc.for_student("U-S0001")
    assert missed.commute.result.decision == "MISSED" and missed.recovery.trigger == "missed"
    assert missed.recovery.recommended is not None
    assert missed.commute.assignment.bus.id == "B05"  # never reassigned
    await _advance(container, 20 * 60)
    late = await svc.for_student("U-S0001")
    assert late.recovery.status == "no_alternative"  # options passed / finished / too late
    await container.simulator.shutdown()


async def test_every_candidate_serves_the_exact_stop_and_direction(container):
    svc = await _recovery(container)
    await _advance(container, 20 * 60)
    # Put B06 on the OPPOSITE direction right beside S27 — it must never be offered.
    state = await container.repos.bus_states.get("B06")
    await container.repos.bus_states.upsert(
        state.model_copy(update={"variant_id": "R3-E", "direction": Direction.FROM_CAMPUS})
    )
    r = (await svc.for_student("U-S0001")).recovery
    for o in [r.recommended, *r.alternatives]:
        d = o.candidate.option.sb.position.direction
        assert d.direction is Direction.TO_CAMPUS and d.stop("S27") is not None
        assert o.candidate.option.sb.match.stop.stop_id == "S27"
    listed = _all_listed(r)
    assert "B06" not in listed  # opposite direction
    assert not {"B01", "B02", "B03", "B04", "B09", "B10"} & set(listed)  # routes not serving S27
    await container.simulator.shutdown()


async def test_live_occupancy_changes_recovery(container):
    svc = await _recovery(container)
    await _advance(container, 20 * 60)
    before = (await svc.for_student("U-S0001")).recovery
    top = before.recommended.candidate.bus_id
    state = await container.repos.bus_states.get(top)
    bus = await container.repos.buses.get(top)
    # Feature 8's occupancy says the recommended bus just filled up
    await container.repos.bus_states.upsert(
        state.model_copy(update={"occupancy_baseline": bus.capacity, "occupancy": bus.capacity})
    )
    after = (await svc.for_student("U-S0001")).recovery
    assert top not in ids(after) and excluded(after)[top] == "full"
    await container.simulator.shutdown()


async def test_alternative_passes_the_stop(container):
    svc = await _recovery(container)
    await _advance(container, 20 * 60)
    first = (await svc.for_student("U-S0001")).recovery.recommended.candidate.bus_id
    await _advance(container, 25 * 60)
    later = (await svc.for_student("U-S0001")).recovery
    assert first not in ids(later)
    assert excluded(later)[first] in ("passed_stop", "trip_completed", "too_late", "at_stop_now")
    await container.simulator.shutdown()


async def test_unassigned_student(container):
    svc = await _recovery(container)
    assert await svc.for_student("U-S0025") is None
    await container.simulator.shutdown()


@pytest.mark.parametrize("decision", ["YES", "LOCATION_UNAVAILABLE", "UNKNOWN"])
def test_not_needed_without_trigger(bundle, decision):
    r = plan(commute(bundle, [(bus_at(bundle, "B11"), pred(9))], decision=decision))
    assert r.status == "not_needed"
