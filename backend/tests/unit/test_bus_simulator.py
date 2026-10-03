"""Synthetic bus simulator: motion model, telemetry → tracking, lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from app.core.clock import DEFAULT_TZ, ManualClock, SimClock
from app.core.config import Settings
from app.core.events import InProcessEventBus
from app.geo import haversine_m
from app.models.common import BusStatus, TripStatus
from app.repositories.memory import memory_repositories
from app.seed import SeedBundle, build_trips, persist_seed
from app.services.bus_simulator import BusSimulator, SimulatorAlreadyRunning
from app.services.tracking import TelemetryIngestService
from app.simulator.bus_agent import build_trip_plan, driver_factor
from app.simulator.traffic import TrafficModel

START = datetime(2026, 10, 5, 7, 15, tzinfo=DEFAULT_TZ)
SERVICE_DATE = START.date()


def settings(**kw) -> Settings:
    return Settings(_env_file=None, app_env="test", **kw)


def trip_plan(bundle: SeedBundle, bus_id: str, *, seed: int = 42, direction_index: int = 0):
    trips = [
        t for t in build_trips(bundle.schedule, bundle.buses, SERVICE_DATE, DEFAULT_TZ) if t.bus_id == bus_id
    ]
    trips.sort(key=lambda t: t.scheduled_start)
    trip = trips[direction_index]
    bus = next(b for b in bundle.buses if b.id == bus_id)
    return build_trip_plan(
        trip,
        bundle.route(trip.route_id),
        bus,
        TrafficModel(bundle.traffic_profiles),
        seed=seed,
        tz=DEFAULT_TZ,
    )


async def make_sim(bundle: SeedBundle, clock=None, **kw):
    repos = memory_repositories()
    await persist_seed(repos, bundle, SERVICE_DATE, DEFAULT_TZ)
    clock = clock or ManualClock(START)
    s = settings(**kw)
    ingest = TelemetryIngestService(repos, InProcessEventBus(), clock, s)
    sim = BusSimulator(repos, clock, ingest, s)
    await sim.reset()
    return sim, repos, clock


async def advance(sim: BusSimulator, clock: ManualClock, seconds: float, step: float = 5.0) -> None:
    """Advance like the real loop: small steps, every grid point emitted."""
    elapsed = 0.0
    while elapsed < seconds:
        clock.advance(step)
        elapsed += step
        await sim.step_until(clock.now())


# =========================================================================== motion model


def test_plan_is_deterministic(bundle: SeedBundle):
    a, b = trip_plan(bundle, "B05"), trip_plan(bundle, "B05")
    assert a.legs == b.legs and a.hold == b.hold and a.occupancy_after == b.occupancy_after
    when = START + timedelta(minutes=17, seconds=13)
    assert a.at(when) == b.at(when)


def test_seed_changes_the_synthetic_variation(bundle: SeedBundle):
    a, c = trip_plan(bundle, "B05", seed=42), trip_plan(bundle, "B05", seed=7)
    assert (a.legs, a.occupancy_after) != (c.legs, c.occupancy_after)


def test_first_stop_waits_until_departure(bundle: SeedBundle):
    p = trip_plan(bundle, "B06")  # departs 07:28 (second R3 bus)
    early = p.at(p.start - timedelta(minutes=10))
    assert early.phase == "pre" and early.stop_seq == 0 and early.distance_m == 0 and early.speed_mps == 0


def test_movement_is_continuous_and_speed_based(bundle: SeedBundle):
    p = trip_plan(bundle, "B05")
    prev = p.at(p.start)
    for s in range(5, int(p.duration_s), 5):
        cur = p.at(p.start + timedelta(seconds=s))
        assert cur.distance_m >= prev.distance_m - 1e-6  # never moves backwards
        assert cur.distance_m - prev.distance_m <= 5 * 30  # no teleporting (≤ 30 m/s)
        if prev.phase == "move" and cur.phase == "move" and cur.speed_mps == prev.speed_mps:
            assert cur.distance_m - prev.distance_m == pytest.approx(prev.speed_mps * 5, rel=1e-6)
        prev = cur
    assert p.at(p.start + timedelta(seconds=p.duration_s + 1)).phase == "done"


def test_position_and_heading_follow_route_geometry(bundle: SeedBundle):
    p = trip_plan(bundle, "B05")
    s = p.at(p.start + timedelta(minutes=6))
    on_line = p.line.interpolate(s.distance_m)
    assert haversine_m(s.lnglat, on_line.point) < 0.01
    assert s.heading_deg == pytest.approx(on_line.heading_deg, abs=0.1)


def test_buses_dwell_at_stops(bundle: SeedBundle):
    p = trip_plan(bundle, "B05")
    dwells = [leg for leg in p.legs if leg.stop_seq is not None]
    assert {leg.stop_seq for leg in dwells} == set(range(1, len(p.variant.stops) - 1))
    leg = dwells[0]
    rs = p.variant.stops[leg.stop_seq]
    expected = rs.dwell_s + (p.hold[1] if p.hold and p.hold[0] == leg.stop_seq else 0)
    assert leg.t1 - leg.t0 == pytest.approx(expected)
    mid = p.at(p.start + timedelta(seconds=(leg.t0 + leg.t1) / 2))
    assert (mid.phase, mid.speed_mps, mid.stop_seq) == ("dwell", 0.0, leg.stop_seq)
    assert mid.distance_m == pytest.approx(rs.distance_along_m)


def test_buses_have_different_deterministic_speeds(bundle: SeedBundle):
    factors = {b.id: driver_factor(42, b.id) for b in bundle.buses}
    assert len({round(f, 6) for f in factors.values()}) == len(factors)
    assert all(0.88 <= f <= 1.12 for f in factors.values())
    assert factors == {b.id: driver_factor(42, b.id) for b in bundle.buses}
    durations = {trip_plan(bundle, b).duration_s for b in ("B05", "B06")}  # same route, different buses
    assert len(durations) == 2


def test_deterministic_delays_exist_somewhere_in_the_fleet(bundle: SeedBundle):
    holds = {b.id: trip_plan(bundle, b.id).hold for b in bundle.buses}
    assert any(holds.values()) and not all(holds.values())
    assert holds == {b.id: trip_plan(bundle, b.id).hold for b in bundle.buses}


def test_occupancy_is_deterministic_and_bounded(bundle: SeedBundle):
    for bus in bundle.buses:
        morning = trip_plan(bundle, bus.id)
        evening = trip_plan(bundle, bus.id, direction_index=1)
        assert morning.occupancy_after == trip_plan(bundle, bus.id).occupancy_after
        for occ in (morning.occupancy_after, evening.occupancy_after):
            assert all(0 <= o <= bus.capacity for o in occ) and occ[-1] == 0
        assert morning.occupancy_after == [*sorted(morning.occupancy_after[:-1]), 0]  # boarding to campus
        assert evening.occupancy_after[0] >= evening.occupancy_after[1]  # alighting going home


# =========================================================================== telemetry → tracking


async def test_initial_state_is_every_bus_at_its_first_stop(bundle: SeedBundle):
    _sim, repos, _ = await make_sim(bundle)
    states = await repos.bus_states.list()
    assert len(states) == 12
    assert {s.status for s in states} == {BusStatus.AT_DEPOT}
    for s in states:
        route = await repos.routes.get(s.route_id)
        assert s.current_stop_id == route.variant(s.variant_id).stops[0].stop_id  # not "passed" early
        assert s.route_progress < 0.01


async def test_simulator_drives_tracking_through_the_ingest_path(bundle: SeedBundle):
    sim, repos, clock = await make_sim(bundle)
    await advance(sim, clock, 6 * 60)
    s = await repos.bus_states.get("B05")
    assert s.status in (BusStatus.EN_ROUTE, BusStatus.DWELLING)
    assert 0 < s.route_progress < 1 and s.distance_along_m > 500
    assert s.next_stop_id is not None and s.current_stop_id is not None
    route = await repos.routes.get("R3")
    stops = route.variant("R3").stops
    nxt = next(x for x in stops if x.stop_id == s.next_stop_id)
    assert nxt.distance_along_m > s.distance_along_m  # next stop is ahead
    trip = await repos.trips.get(s.trip_id)
    assert trip.status is TripStatus.ACTIVE and trip.actual_start is not None
    telemetry = await repos.telemetry.recent("B05", since=START)
    assert len(telemetry) >= 6 * 60 / 5 and {t.meta.source.value for t in telemetry} == {"sim"}


async def test_tracking_marks_dwelling_and_completion(bundle: SeedBundle):
    sim, repos, clock = await make_sim(bundle, sim_gps_noise_sigma_m=0)
    p = sim.plan("B05").trips[0]
    dwell = next(leg for leg in p.legs if leg.stop_seq == 2)
    await advance(sim, clock, dwell.t0 + 10)
    s = await repos.bus_states.get("B05")
    assert s.status is BusStatus.DWELLING and s.current_stop_id == p.variant.stops[2].stop_id
    assert s.next_stop_id == p.variant.stops[3].stop_id and s.speed_mps == 0
    await advance(sim, clock, p.duration_s - dwell.t0 + 30)
    s = await repos.bus_states.get("B05")
    assert s.status is BusStatus.COMPLETED and s.route_progress == pytest.approx(1.0, abs=0.01)
    assert (await repos.trips.get(p.trip.id)).status is TripStatus.COMPLETED
    assert s.occupancy == 0
    # after completion the "phone" stops reporting until the next trip
    count = len(await repos.telemetry.for_trip(p.trip.id))
    await advance(sim, clock, 300)
    assert len(await repos.telemetry.for_trip(p.trip.id)) == count


async def test_same_inputs_give_identical_bus_state(bundle: SeedBundle):
    a, repos_a, clock_a = await make_sim(bundle)
    b, repos_b, clock_b = await make_sim(bundle)
    await advance(a, clock_a, 900, step=5)
    await advance(b, clock_b, 900, step=15)  # different stepping, same grid → same result
    sa = {s.id: s.model_dump() for s in await repos_a.bus_states.list()}
    sb = {s.id: s.model_dump() for s in await repos_b.bus_states.list()}
    assert sa == sb


async def test_delays_are_reported_from_the_timetable(bundle: SeedBundle):
    sim, repos, clock = await make_sim(bundle)
    await advance(sim, clock, 45 * 60, step=20)
    delays = {s.id: s.delay_s for s in await repos.bus_states.list()}
    assert len(set(delays.values())) > 3  # buses arrive at different times
    assert max(delays.values()) >= 300  # some bus is DELAYED (≥ 5 min)


# =========================================================================== lifecycle


async def test_pause_reset_and_speed_use_the_sim_clock(bundle: SeedBundle):
    sim, repos, clock = await make_sim(bundle)
    await sim.pause()
    assert sim.status().paused and clock.paused
    await sim.start()
    assert not sim.status().paused
    sim.set_speed(20)
    assert sim.status().speed == 20
    with pytest.raises(ValueError):
        sim.set_speed(3)
    await advance(sim, clock, 600)
    assert (await repos.bus_states.get("B05")).status is not BusStatus.AT_DEPOT
    await sim.reset()
    assert sim.status().sim_time == START
    assert (await repos.bus_states.get("B05")).status is BusStatus.AT_DEPOT
    assert {t.status for t in await repos.trips.on_date(SERVICE_DATE)} == {TripStatus.SCHEDULED}
    await sim.shutdown()


async def test_real_loop_runs_once_and_shuts_down_cleanly(bundle: SeedBundle):
    real = {"t": 0.0}
    clock = SimClock(START, speed=20, real_monotonic=lambda: real["t"])
    sim, _repos, _ = await make_sim(bundle, clock=clock)
    assert sim.ensure_loop() is True
    assert sim.ensure_loop() is False  # no duplicate task
    task = sim._task
    real["t"] += 3  # 3 real s at 20× = 60 sim s
    for _ in range(20):
        await asyncio.sleep(0.05)
        if sim.status().emissions > 1:
            break
    assert sim.status().emissions > 1
    other, *_ = await make_sim(bundle, clock=SimClock(START))
    with pytest.raises(SimulatorAlreadyRunning):
        other.ensure_loop()  # never two simulators running in one process
    await sim.shutdown()
    assert task.done() and not sim.task_running
    other.ensure_loop()  # allowed once the first has stopped
    await other.shutdown()


async def test_reset_recreates_missing_trips(bundle: SeedBundle):
    sim, repos, _ = await make_sim(bundle)
    await repos.trips.delete_all()
    await sim.reset()
    assert len(await repos.trips.on_date(SERVICE_DATE)) == 24
    assert len(await repos.bus_states.list()) == 12
