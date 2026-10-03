"""QR boarding + live occupancy (Feature 8): rules, duplicates, concurrency, simulator interplay."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.core.auth import Principal
from app.models.common import BusStatus, Role, TripStatus
from app.services.boarding_service import BoardingRejected, BoardingService, QrPayload, boarding_id
from app.services.capacity import (
    available_seats,
    is_full,
    live_occupancy,
    occupancy_percentage,
    occupancy_percentage_display,
)
from tests.unit.test_bus_comparison import _advance

STUDENT = "U-S0001"  # assigned B05 · R3 · S27 Sholinganallur Junction
ME = Principal(user_id=STUDENT, role=Role.STUDENT, name="Test")


# =========================================================================== pure occupancy rules


def test_occupancy_rule():
    assert live_occupancy(baseline=30, boarded=2, capacity=50, trip_completed=False) == 32
    assert live_occupancy(baseline=49, boarded=3, capacity=50, trip_completed=False) == 50  # capped
    assert live_occupancy(baseline=0, boarded=4, capacity=50, trip_completed=True) == 0  # alighted
    assert live_occupancy(baseline=-1, boarded=-2, capacity=50, trip_completed=False) == 0


def test_available_seats_and_percentage():
    assert available_seats(38, 50) == 12 and available_seats(55, 50) == 0
    assert occupancy_percentage_display(38, 50) == 76
    assert occupancy_percentage_display(1, 3) == 33  # rounded, no decimals
    assert occupancy_percentage(10, 0) is None and occupancy_percentage_display(10, 0) is None
    assert is_full(50, 50) and not is_full(49, 50)


# =========================================================================== service fixtures


async def _svc(container) -> BoardingService:
    from app.main import attach_simulator

    attach_simulator(container)
    await container.simulator.reset()
    await _advance(container, 3 * 60)  # B05 has left its first stop; S27 still ahead
    return container.boarding()


async def _qr(container, student=STUDENT, **over) -> QrPayload:
    state = await container.repos.bus_states.get("B05")
    base = {
        "student_id": student,
        "bus_id": "B05",
        "trip_id": state.trip_id,
        "timestamp": container.clock.now(),
        "stop_id": "S27",
    }
    return QrPayload(**{**base, **over})


async def _reject(svc, payload, code, principal=ME):
    with pytest.raises(BoardingRejected) as exc:
        await svc.scan(principal, payload)
    assert exc.value.code == code, exc.value.message
    return exc.value


async def _other_students_on_b05(container, n):
    assigned = await container.repos.student_assignments.for_bus("B05")
    ids = sorted(a.id for a in assigned if a.id != STUDENT and a.boarding_stop_id == "S27")
    assert len(ids) >= n, "seed should put several B05 students at S27"
    return ids[:n]


# =========================================================================== valid boarding


async def test_valid_boarding_records_event_and_increments_once(container):
    svc = await _svc(container)
    before = await container.repos.bus_states.get("B05")
    r = await svc.scan(ME, await _qr(container))
    assert r.status == "boarded"
    assert r.event.id == boarding_id(before.trip_id, STUDENT)  # server-derived, deterministic
    assert (r.event.stop_id, r.event.bus_id, r.event.trip_id) == ("S27", "B05", before.trip_id)
    assert r.occupancy.occupancy == before.occupancy + 1 and r.occupancy.boarded == 1
    assert r.occupancy.available_seats == 50 - r.occupancy.occupancy
    assert r.occupancy.occupancy_percentage == round(100 * r.occupancy.occupancy / 50)
    stored = await container.repos.boarding_events.for_student_trip(STUDENT, before.trip_id)
    assert stored is not None and stored.scanner == "simulated"  # persisted
    state = await container.repos.bus_states.get("B05")
    assert state.occupancy == before.occupancy + 1  # visible through the existing bus state
    await container.simulator.shutdown()


async def test_stop_id_is_optional_and_taken_from_the_assignment(container):
    svc = await _svc(container)
    r = await svc.scan(ME, await _qr(container, stop_id=None))
    assert r.status == "boarded" and r.event.stop_id == "S27"
    await container.simulator.shutdown()


# =========================================================================== rejections


async def test_invalid_student_and_non_student_role(container):
    svc = await _svc(container)
    await _reject(svc, await _qr(container, student="U-S0002"), "invalid_student")  # not the caller
    ghost = Principal(user_id="U-NOPE", role=Role.STUDENT)
    await _reject(svc, await _qr(container, student="U-NOPE"), "invalid_student", ghost)
    admin = Principal(user_id="U-A1", role=Role.ADMIN)
    await _reject(svc, await _qr(container), "not_a_student", admin)
    driver = Principal(user_id="U-D05", role=Role.DRIVER)
    await _reject(svc, await _qr(container), "not_a_student", driver)
    await container.simulator.shutdown()


async def test_unassigned_student(container):
    svc = await _svc(container)
    p = Principal(user_id="U-S0025", role=Role.STUDENT)
    await _reject(svc, await _qr(container, student="U-S0025"), "unassigned", p)
    await container.simulator.shutdown()


async def test_wrong_bus(container):
    svc = await _svc(container)
    b06 = await container.repos.bus_states.get("B06")
    err = await _reject(svc, await _qr(container, bus_id="B06", trip_id=b06.trip_id), "wrong_bus")
    assert err.status_code == 403
    await container.simulator.shutdown()


async def test_wrong_trip_mismatch_and_unknown_trip(container):
    svc = await _svc(container)
    await _reject(svc, await _qr(container, trip_id="T-NOPE"), "trip_not_found")
    b06 = await container.repos.bus_states.get("B06")  # B06's trip, claimed for B05
    await _reject(svc, await _qr(container, trip_id=b06.trip_id), "bus_trip_mismatch")
    service_date = container.clock.local_now().date()
    trips = await container.repos.trips.for_bus_on("B05", service_date)
    evening = next(t for t in trips if t.variant_id != "R3")  # B05's own trip, other direction
    await _reject(svc, await _qr(container, trip_id=evening.id), "wrong_trip")
    await container.simulator.shutdown()


async def test_inactive_trip(container):
    svc = await _svc(container)
    qr = await _qr(container)
    await container.repos.trips.set_status(qr.trip_id, TripStatus.COMPLETED, container.clock.now())
    await _reject(svc, qr, "trip_inactive")
    await container.simulator.shutdown()


async def test_wrong_stop_and_passed_stop(container):
    svc = await _svc(container)
    err = await _reject(svc, await _qr(container, stop_id="S08"), "invalid_stop")
    assert err.status_code == 422
    await _advance(container, 36 * 60)  # B05 passes S27 (~07:45) but its trip is still running
    state = await container.repos.bus_states.get("B05")
    if state.status is not BusStatus.COMPLETED:
        await _reject(svc, await _qr(container), "stop_passed")
    else:
        await _reject(svc, await _qr(container), "trip_inactive")
    await container.simulator.shutdown()


async def test_bus_full(container):
    svc = await _svc(container)
    state = await container.repos.bus_states.get("B05")
    await container.repos.bus_states.upsert(
        state.model_copy(update={"occupancy_baseline": 50, "occupancy": 50})
    )
    await _reject(svc, await _qr(container), "bus_full")
    assert await container.repos.boarding_events.count_for_trip(state.trip_id) == 0  # no event
    assert (await container.repos.bus_states.get("B05")).occupancy == 50
    await container.simulator.shutdown()


# =========================================================================== duplicates & concurrency


async def test_duplicate_scan_is_idempotent(container):
    svc = await _svc(container)
    first = await svc.scan(ME, await _qr(container))
    again = await svc.scan(ME, await _qr(container, timestamp=container.clock.now() + timedelta(seconds=9)))
    assert again.status == "already_boarded" and again.event.id == first.event.id
    assert again.occupancy.occupancy == first.occupancy.occupancy  # not incremented
    assert await container.repos.boarding_events.count_for_trip(first.event.trip_id) == 1
    await container.simulator.shutdown()


async def test_concurrent_duplicate_scans_board_once(container):
    svc = await _svc(container)
    qr = await _qr(container)
    before = (await container.repos.bus_states.get("B05")).occupancy
    results = await asyncio.gather(*(svc.scan(ME, qr) for _ in range(5)))
    assert sorted(r.status for r in results).count("boarded") == 1
    assert await container.repos.boarding_events.count_for_trip(qr.trip_id) == 1
    assert (await container.repos.bus_states.get("B05")).occupancy == before + 1
    await container.simulator.shutdown()


async def test_last_seat_race_never_overfills(container):
    svc = await _svc(container)
    state = await container.repos.bus_states.get("B05")
    await container.repos.bus_states.upsert(
        state.model_copy(update={"occupancy_baseline": 49, "occupancy": 49})
    )
    a, b = STUDENT, (await _other_students_on_b05(container, 1))[0]
    pa, pb = Principal(user_id=a, role=Role.STUDENT), Principal(user_id=b, role=Role.STUDENT)
    results = await asyncio.gather(
        svc.scan(pa, await _qr(container, student=a)),
        svc.scan(pb, await _qr(container, student=b)),
        return_exceptions=True,
    )
    boarded = [r for r in results if not isinstance(r, Exception)]
    full = [r for r in results if isinstance(r, BoardingRejected) and r.code == "bus_full"]
    assert len(boarded) == 1 and len(full) == 1
    assert await container.repos.boarding_events.count_for_trip(state.trip_id) == 1
    assert (await container.repos.bus_states.get("B05")).occupancy == 50
    await container.simulator.shutdown()


async def test_deterministic_ids_and_results(container):
    svc = await _svc(container)
    r = await svc.scan(ME, await _qr(container))
    assert r.event.id == f"BRD-{r.event.trip_id}-{STUDENT}"
    await container.simulator.shutdown()


# =========================================================================== simulator interplay


async def test_simulator_ticks_never_erase_a_boarding(container):
    svc = await _svc(container)
    r = await svc.scan(ME, await _qr(container))
    for _ in range(6):
        await _advance(container, 60)
        s = await container.repos.bus_states.get("B05")
        assert s.boarded_count == 1
        assert s.occupancy == min(50, s.occupancy_baseline + 1)  # baseline moves, boarding stays
    assert r.status == "boarded"
    await container.simulator.shutdown()


async def test_reading_occupancy_never_increments(container):
    svc = await _svc(container)
    await svc.scan(ME, await _qr(container))
    reads = [await svc.occupancy("B05") for _ in range(5)]
    assert {o.boarded for o in reads} == {1} and len({o.occupancy for o in reads}) == 1
    assert reads[0].source == "synthetic_baseline+qr"
    await container.simulator.shutdown()


async def test_reset_clears_boardings_consistently(container):
    svc = await _svc(container)
    r = await svc.scan(ME, await _qr(container))
    await container.simulator.reset()
    assert await container.repos.boarding_events.count_for_trip(r.event.trip_id) == 0
    await _advance(container, 3 * 60)
    s = await container.repos.bus_states.get("B05")
    assert s.boarded_count == 0 and s.occupancy == s.occupancy_baseline
    again = await svc.scan(ME, await _qr(container))  # the replayed trip can be boarded again
    assert again.status == "boarded"
    await container.simulator.shutdown()


async def test_boarded_riders_alight_when_the_trip_completes(container):
    svc = await _svc(container)
    await svc.scan(ME, await _qr(container))
    await _advance(container, 60 * 60)
    s = await container.repos.bus_states.get("B05")
    if s.status is BusStatus.COMPLETED:
        assert s.occupancy == min(50, s.occupancy_baseline)
    await container.simulator.shutdown()


# =========================================================================== reads


async def test_trip_boarding_visibility(container):
    svc = await _svc(container)
    r = await svc.scan(ME, await _qr(container))
    (other,) = await _other_students_on_b05(container, 1)
    await svc.scan(Principal(user_id=other, role=Role.STUDENT), await _qr(container, student=other))
    trip = r.event.trip_id
    admin = await svc.trip_boarding(trip, Principal(user_id="U-A1", role=Role.ADMIN))
    assert admin.visibility == "all" and {e.student_id for e in admin.events} == {STUDENT, other}
    mine = await svc.trip_boarding(trip, ME)
    assert mine.visibility == "own" and [e.student_id for e in mine.events] == [STUDENT]
    assert mine.total_boarded == 2
    drv = await svc.trip_boarding(trip, Principal(user_id="U-D05", role=Role.DRIVER))
    assert drv.events == [] and drv.total_boarded == 2
    with pytest.raises(BoardingRejected):
        await svc.trip_boarding("T-NOPE", ME)
    await container.simulator.shutdown()


async def test_student_scanner_state(container):
    svc = await _svc(container)
    s = await svc.for_student(STUDENT)
    assert s.ready and s.trip_id and s.boarded is None and s.occupancy.bus_id == "B05"
    await svc.scan(ME, await _qr(container))
    s = await svc.for_student(STUDENT)
    assert not s.ready and s.boarded is not None
    assert await svc.for_student("U-S0025") is None
    await container.simulator.shutdown()
