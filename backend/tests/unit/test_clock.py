from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime

import pytest

from app.core.clock import (
    ALLOWED_SIM_SPEEDS,
    DEFAULT_TZ,
    Clock,
    ManualClock,
    RealClock,
    SimClock,
    derive_seed,
    resolve_sim_start,
)

START = datetime(2026, 10, 5, 7, 15, tzinfo=DEFAULT_TZ)


class FakeReal:
    """Controllable stand-in for time.monotonic()."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def real() -> FakeReal:
    return FakeReal()


@pytest.fixture
def sim(real: FakeReal) -> SimClock:
    return SimClock(START, speed=5, seed=42, real_monotonic=real)


# --------------------------------------------------------------------------- start date


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 1), date(2026, 10, 2)),  # Thu → Fri
        (date(2026, 10, 2), date(2026, 10, 5)),  # Fri → Mon
        (date(2026, 10, 3), date(2026, 10, 5)),  # Sat → Mon
        (date(2026, 10, 4), date(2026, 10, 5)),  # Sun → Mon
    ],
)
def test_auto_start_is_next_weekday(today, expected):
    start = resolve_sim_start("auto", dtime(7, 15), DEFAULT_TZ, today=today)
    assert start.date() == expected
    assert start.time() == dtime(7, 15)
    assert start.utcoffset() == timedelta(hours=5, minutes=30)


def test_explicit_start_date():
    start = resolve_sim_start("2026-12-01", dtime(16, 30), DEFAULT_TZ)
    assert start == datetime(2026, 12, 1, 16, 30, tzinfo=DEFAULT_TZ)


# --------------------------------------------------------------------------- SimClock


def test_times_are_utc_aware_and_local_is_ist(sim: SimClock):
    assert sim.now().tzinfo is UTC
    assert sim.now() == START
    assert sim.local_now().strftime("%H:%M %z") == "07:15 +0530"


def test_runs_at_configured_speed(sim: SimClock, real: FakeReal):
    real.t += 10  # 10 real seconds at 5x
    assert sim.now() == START + timedelta(seconds=50)
    assert sim.monotonic() == pytest.approx(50)


def test_speed_change_is_continuous(sim: SimClock, real: FakeReal):
    real.t += 10
    before = sim.now()
    sim.set_speed(20)
    assert sim.now() == before
    real.t += 1
    assert sim.now() == before + timedelta(seconds=20)


@pytest.mark.parametrize("bad", [0, 3, 7, 50, -1])
def test_only_allowed_speeds(sim: SimClock, bad):
    with pytest.raises(ValueError):
        sim.set_speed(bad)
    with pytest.raises(ValueError):
        SimClock(START, speed=bad)


def test_allowed_speeds_match_spec():
    assert ALLOWED_SIM_SPEEDS == (1, 2, 5, 10, 20)


def test_pause_and_resume(sim: SimClock, real: FakeReal):
    real.t += 2
    sim.pause()
    frozen = sim.now()
    real.t += 100
    assert sim.now() == frozen and sim.paused
    sim.resume()
    real.t += 1
    assert sim.now() == frozen + timedelta(seconds=5)


def test_advance_and_fast_forward(sim: SimClock):
    sim.advance(60)
    assert sim.local_now().time() == dtime(7, 16)
    sim.fast_forward_to(dtime(7, 42))  # "07:42 morning rush"
    assert sim.local_now().time() == dtime(7, 42)
    with pytest.raises(ValueError):
        sim.fast_forward_to(dtime(7, 0))
    with pytest.raises(ValueError):
        sim.advance(-1)


def test_reset_returns_to_start(sim: SimClock, real: FakeReal):
    sim.advance(3600)
    real.t += 50
    sim.reset()
    assert sim.now() == START


def test_seconds_of_day_is_campus_local(sim: SimClock):
    assert sim.seconds_of_day() == 7 * 3600 + 15 * 60


def test_naive_start_rejected():
    with pytest.raises(ValueError):
        SimClock(datetime(2026, 10, 5, 7, 15))


# --------------------------------------------------------------------------- determinism


def test_rng_streams_are_deterministic_and_independent():
    a = SimClock(START, seed=42).rng("bus", "B03", "noise")
    b = SimClock(START, seed=42).rng("bus", "B03", "noise")
    c = SimClock(START, seed=42).rng("bus", "B04", "noise")
    seq_a = [a.random() for _ in range(5)]
    assert seq_a == [b.random() for _ in range(5)]
    assert seq_a != [c.random() for _ in range(5)]


def test_rng_does_not_depend_on_calendar_date():
    monday = SimClock(START, seed=42)
    later = SimClock(START + timedelta(days=37), seed=42)
    assert monday.rng("MORNING_RUSH").random() == later.rng("MORNING_RUSH").random()


def test_derive_seed_depends_on_seed_and_scope():
    assert derive_seed(42, "x") == derive_seed(42, "x")
    assert derive_seed(42, "x") != derive_seed(43, "x")
    assert derive_seed(42, "x", "y") != derive_seed(42, "xy")


# --------------------------------------------------------------------------- other clocks


async def test_manual_clock_only_moves_when_told():
    clock = ManualClock(START)
    assert clock.now() == START
    await clock.sleep(30)
    assert clock.now() == START + timedelta(seconds=30)


def test_clocks_satisfy_protocol():
    assert isinstance(RealClock(), Clock)
    assert isinstance(SimClock(START), Clock)
    assert RealClock().now().tzinfo is UTC
