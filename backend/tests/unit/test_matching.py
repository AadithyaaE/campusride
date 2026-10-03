"""Stop ↔ route-direction ↔ bus matching (pure rules + service over real seeded routes)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.errors import NotFoundError
from app.models import BusState, GeoPoint
from app.models.common import BusStatus, Direction, StopProximity
from app.seed import SeedBundle
from app.services.matching import MatchingService, locate, match_stop, stops_around

RADIUS = 40.0
APPROACH = 1_000.0
TS = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)


def state(
    variant_id: str,
    d: float,
    status: BusStatus = BusStatus.EN_ROUTE,
    bus_id: str = "B03",
    lnglat=(80.2, 12.9),
):
    route_id = variant_id.removesuffix("-E")
    return BusState(
        id=bus_id,
        trip_id=f"T-{variant_id}",
        route_id=route_id,
        variant_id=variant_id,
        direction=Direction.FROM_CAMPUS if variant_id.endswith("-E") else Direction.TO_CAMPUS,
        ts=TS,
        last_seen=TS,
        location=GeoPoint.of(*lnglat),
        distance_along_m=d,
        speed_mps=0.0 if status in (BusStatus.DWELLING, BusStatus.AT_DEPOT, BusStatus.COMPLETED) else 8.0,
        status=status,
    )


def direction(bundle: SeedBundle, variant_id: str):
    return bundle.route(variant_id.removesuffix("-E")).variant(variant_id)


def m(bundle, variant_id, d, stop_id, status=BusStatus.EN_ROUTE):
    return match_stop(
        state(variant_id, d, status),
        direction(bundle, variant_id),
        stop_id,
        radius_m=RADIUS,
        approaching_m=APPROACH,
    )


def dist(bundle, variant_id, stop_id) -> float:
    return direction(bundle, variant_id).stop(stop_id).distance_along_m


# =========================================================================== serving


def test_bus_serves_stop_on_its_direction(bundle: SeedBundle):
    assert m(bundle, "R2", 100, "S12") is not None  # Pallikaranai is on R2


def test_bus_does_not_serve_stop_off_its_direction(bundle: SeedBundle):
    assert m(bundle, "R2", 100, "S20") is None  # Tidel Park is R3/R4 only
    assert m(bundle, "R2", 100, "S01") is None  # Tambaram is R1 only


def test_nearby_but_unrelated_bus_is_not_matched(bundle: SeedBundle):
    """A bus physically AT a stop's coordinates but on another route does not serve it."""
    s14 = bundle.stop("S14")  # Jalladianpet — R2 only
    r1_bus = state("R1", 5_000, lnglat=s14.location.lnglat)
    assert match_stop(r1_bus, direction(bundle, "R1"), "S14", radius_m=RADIUS, approaching_m=APPROACH) is None


# =========================================================================== direction


def test_direction_specific_stop_ordering(bundle: SeedBundle):
    to, frm = direction(bundle, "R2"), direction(bundle, "R2-E")
    assert to.stops[0].stop_id == "S09" and to.stops[-1].stop_id == "S00"
    assert frm.stops[0].stop_id == "S00" and frm.stops[-1].stop_id == "S09"
    assert [s.stop_id for s in frm.stops] == [s.stop_id for s in reversed(to.stops)]


def test_same_stop_is_ahead_in_one_direction_and_behind_in_the_other(bundle: SeedBundle):
    # Bus 1 km into its trip: Pallikaranai (S12) is ahead on R2 (to campus) …
    to_campus = m(bundle, "R2", 1_000, "S12")
    assert to_campus.position == "ahead"
    # … and on R2-E a bus 1 km out of campus also has S12 ahead, but much further
    from_campus = m(bundle, "R2-E", 1_000, "S12")
    assert from_campus.position == "ahead"
    assert from_campus.distance_to_stop_m != to_campus.distance_to_stop_m
    # A bus past S12 on R2 has it behind
    assert m(bundle, "R2", dist(bundle, "R2", "S12") + 500, "S12").position == "behind"


def test_reverse_direction_next_stop_follows_reverse_order(bundle: SeedBundle):
    frm = direction(bundle, "R2-E")
    d = (frm.stops[1].distance_along_m + frm.stops[2].distance_along_m) / 2
    p = locate(state("R2-E", d), frm, RADIUS)
    assert (p.previous.stop_id, p.current.stop_id, p.next.stop_id) == (
        frm.stops[0].stop_id,
        frm.stops[1].stop_id,
        frm.stops[2].stop_id,
    )
    assert (p.current.stop_id, p.next.stop_id) == ("S08", "S14")  # campus → Medavakkam → Jalladianpet


# =========================================================================== current / next / previous


def test_between_stops(bundle: SeedBundle):
    to = direction(bundle, "R2")
    d = (to.stops[3].distance_along_m + to.stops[4].distance_along_m) / 2
    p = locate(state("R2", d), to, RADIUS)
    assert p.at_stop is None
    assert (p.previous.seq, p.current.seq, p.next.seq) == (2, 3, 4)
    assert p.distance_to_next_m == pytest.approx(to.stops[4].distance_along_m - d, abs=0.1)


def test_dwelling_at_a_stop(bundle: SeedBundle):
    to = direction(bundle, "R2")
    p = locate(state("R2", to.stops[4].distance_along_m + 5, BusStatus.DWELLING), to, RADIUS)
    assert p.at_stop.seq == 4 and p.current.seq == 4
    assert (p.previous.seq, p.next.seq) == (3, 5)


def test_first_stop_before_departure(bundle: SeedBundle):
    to = direction(bundle, "R2")
    p = locate(state("R2", 0, BusStatus.AT_DEPOT), to, RADIUS)
    assert p.at_stop.seq == 0 and p.current.seq == 0 and p.previous is None and p.next.seq == 1
    first = m(bundle, "R2", 0, "S09", BusStatus.AT_DEPOT)
    assert first.proximity is StopProximity.AT_STOP and first.dwelling_at_stop and first.stops_away == 0
    # not "passed" before the trip starts
    assert m(bundle, "R2", 0, "S10", BusStatus.AT_DEPOT).position == "ahead"


def test_last_stop_completed_trip(bundle: SeedBundle):
    to = direction(bundle, "R2")
    p = locate(state("R2", to.stops[-1].distance_along_m, BusStatus.COMPLETED), to, RADIUS)
    assert p.current.stop_id == "S00" and p.next is None and p.previous.stop_id == "S08"
    assert (
        m(bundle, "R2", to.stops[-1].distance_along_m, "S00", BusStatus.COMPLETED).proximity
        is StopProximity.AT_STOP
    )
    assert (
        m(bundle, "R2", to.stops[-1].distance_along_m, "S12", BusStatus.COMPLETED).proximity
        is StopProximity.PASSED_STOP
    )


def test_stops_around_is_shared_with_tracking(bundle: SeedBundle):
    to = direction(bundle, "R2")
    a = stops_around(to, to.stops[2].distance_along_m + 10, RADIUS)
    assert a.near.seq == 2 and a.last_reached.seq == 2 and a.next.seq == 3


# =========================================================================== proximity thresholds


@pytest.mark.parametrize(
    ("offset", "expected", "position"),
    [
        (5_000, StopProximity.FAR_FROM_STOP, "ahead"),
        (1_001, StopProximity.FAR_FROM_STOP, "ahead"),
        (1_000, StopProximity.APPROACHING_STOP, "ahead"),
        (41, StopProximity.APPROACHING_STOP, "ahead"),
        (40, StopProximity.AT_STOP, "current"),
        (0, StopProximity.AT_STOP, "current"),
        (-40, StopProximity.AT_STOP, "current"),
        (-41, StopProximity.PASSED_STOP, "behind"),
        (-1_500, StopProximity.PASSED_STOP, "behind"),
    ],
)
def test_proximity_thresholds(bundle: SeedBundle, offset, expected, position):
    stop_d = dist(bundle, "R2", "S08")  # ~7.4 km along R2
    r = m(bundle, "R2", stop_d - offset, "S08")
    assert (r.proximity, r.position) == (expected, position)
    assert r.stop_offset_m == pytest.approx(offset, abs=0.1)
    if expected is StopProximity.PASSED_STOP:
        assert r.distance_to_stop_m is None and r.stops_away is None
    else:
        assert r.distance_to_stop_m == pytest.approx(max(0, offset), abs=0.1)


def test_moving_through_a_stop_is_at_stop_but_not_dwelling(bundle: SeedBundle):
    r = m(bundle, "R2", dist(bundle, "R2", "S12") - 10, "S12", BusStatus.EN_ROUTE)
    assert r.proximity is StopProximity.AT_STOP and r.dwelling_at_stop is False
    d = m(bundle, "R2", dist(bundle, "R2", "S12") - 10, "S12", BusStatus.DWELLING)
    assert d.dwelling_at_stop is True


def test_stops_away_and_progress(bundle: SeedBundle):
    to = direction(bundle, "R2")
    d = (to.stops[1].distance_along_m + to.stops[2].distance_along_m) / 2
    r = m(bundle, "R2", d, "S08")  # S08 is stop 6 → stops 2..6 ahead = 5
    assert r.stops_away == 5
    assert r.progress_to_stop == pytest.approx(d / to.stop("S08").distance_along_m, abs=1e-4)
    assert m(bundle, "R2", d, to.stops[2].stop_id).stops_away == 1  # it is the next stop


# ====================================================================== service (simulator state)


async def test_multiple_buses_serve_a_shared_stop(container):
    from app.main import attach_simulator

    attach_simulator(container)
    await container.simulator.reset()
    svc = MatchingService(container.repos, container.settings)
    serving = await svc.buses_serving_stop("S08")  # Medavakkam: R1, R2, R5 (to campus at 07:15)
    assert {sb.state.variant_id for sb in serving} == {"R1", "R2", "R5"}
    assert sorted(sb.bus.id for sb in serving) == ["B01", "B02", "B03", "B04", "B09", "B10"]
    assert all(sb.match.stop.stop_id == "S08" and sb.match.position == "ahead" for sb in serving)
    assert await svc.buses_serving_stop("S08", direction=Direction.FROM_CAMPUS) == []  # morning
    assert {sb.bus.id for sb in await svc.buses_serving_stop("S27")} == {
        "B05",
        "B06",
        "B07",
        "B08",
        "B11",
        "B12",
    }
    await container.simulator.shutdown()


async def test_service_ignores_geography_and_checks_ids(container):
    svc = MatchingService(container.repos, container.settings)
    s14 = (await container.repos.stops.get("S14")).location.lnglat
    await container.repos.bus_states.upsert(state("R1", 3_000, bus_id="B01", lnglat=s14))
    assert await svc.buses_serving_stop("S14") == []  # B01 sits on S14's coordinates but runs R1
    assert await svc.bus_serves_stop("B01", "S14") is None
    assert (await svc.bus_serves_stop("B01", "S08")).match.position == "ahead"
    assert await svc.bus_serves_stop("B02", "S08") is None  # no live state yet
    with pytest.raises(NotFoundError):
        await svc.bus_serves_stop("B99", "S08")
    with pytest.raises(NotFoundError):
        await svc.buses_serving_stop("S99")


async def test_student_view_assigned_and_unassigned(container):
    svc = MatchingService(container.repos, container.settings)
    a = await container.repos.student_assignments.get("U-S0001")  # B05 · R3 · S27
    await container.repos.bus_states.upsert(state("R3", 1_000, bus_id="B05"))
    await container.repos.bus_states.upsert(state("R4", 1_000, bus_id="B07"))
    await container.repos.bus_states.upsert(state("R6-E", 500, bus_id="B11"))  # other direction
    r = await svc.for_student("U-S0001")
    assert r.my_bus.bus.id == a.assigned_bus_id and r.my_bus.match.stop.stop_id == "S27"
    assert [sb.bus.id for sb in r.others] == ["B07"]  # same direction only; B11 is going home
    assert await svc.for_student("U-S0025") is None  # unassigned — nothing invented


async def test_assigned_bus_on_the_other_direction_is_not_serving(container):
    svc = MatchingService(container.repos, container.settings)
    await container.repos.bus_states.upsert(state("R3-E", 2_000, bus_id="B05"))
    r = await svc.for_student("U-S0001")
    assert r.my_bus.bus.id == "B05" and r.my_bus.match is None
    assert r.my_bus.position.direction.variant_id == "R3-E"
