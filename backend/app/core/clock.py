"""The one source of time for the whole backend.

Nothing outside this module calls ``datetime.now()``. Services receive a
``Clock`` and ask it for the time, which is what makes demos repeatable and
lets the simulator fast-forward to "07:42, morning rush".

* ``RealClock``   — wall-clock time (real buses, production).
* ``SimClock``    — simulated time: starts at a configured campus-local
  moment, runs at 1/2/5/10/20× and can pause, fast-forward and reset.
* ``ManualClock`` — a ``SimClock`` that only moves when told to (tests).

Timestamps are timezone-aware UTC; ``local_now()`` gives campus time.

Determinism: ``rng(*scope)`` derives an independent random stream from
SEED + scope strings. Callers scope by scenario / bus / time-of-day — never
by calendar date — so a scenario behaves identically on any day it is run.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import time as _time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

ALLOWED_SIM_SPEEDS: tuple[int, ...] = (1, 2, 5, 10, 20)
DEFAULT_TZ = ZoneInfo("Asia/Kolkata")


@runtime_checkable
class Clock(Protocol):
    @property
    def tz(self) -> ZoneInfo: ...

    @property
    def speed(self) -> float: ...

    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        ...

    def local_now(self) -> datetime:
        """Current time in the campus timezone."""
        ...

    def monotonic(self) -> float:
        """Seconds on this clock's own timeline; only differences are meaningful."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Sleep for ``seconds`` of *clock* time."""
        ...


class RealClock:
    def __init__(self, tz: ZoneInfo = DEFAULT_TZ) -> None:
        self._tz = tz

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    @property
    def speed(self) -> float:
        return 1.0

    def now(self) -> datetime:
        return datetime.now(UTC)

    def local_now(self) -> datetime:
        return self.now().astimezone(self._tz)

    def monotonic(self) -> float:
        return _time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))


def derive_seed(seed: int, *scope: str) -> int:
    """Stable 64-bit seed from a base seed and scope strings (independent of PYTHONHASHSEED)."""
    material = "|".join([str(seed), *scope]).encode()
    return int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(), "big")


def resolve_sim_start(
    start_date: str,
    start_time: dtime,
    tz: ZoneInfo = DEFAULT_TZ,
    today: date | None = None,
) -> datetime:
    """Resolve SIM_START_DATE/SIM_START_TIME to an aware campus-local datetime.

    ``"auto"`` → the next weekday strictly after ``today`` (campus date).
    ``"YYYY-MM-DD"`` → that date.
    """
    if start_date == "auto":
        d = today or datetime.now(tz).date()
        d += timedelta(days=1)
        while d.weekday() >= 5:  # Saturday=5, Sunday=6
            d += timedelta(days=1)
    else:
        d = date.fromisoformat(start_date)
    return datetime.combine(d, start_time, tzinfo=tz)


class SimClock:
    """Simulated time anchored to a real monotonic clock.

    ``now() = sim_anchor + (real_now - real_anchor) × speed`` while running.
    Every control operation re-anchors first, so time is always continuous.
    """

    def __init__(
        self,
        start: datetime,
        *,
        speed: float = 5,
        seed: int = 42,
        tz: ZoneInfo = DEFAULT_TZ,
        paused: bool = False,
        real_monotonic: Callable[[], float] = _time.monotonic,
    ) -> None:
        if start.tzinfo is None:
            raise ValueError("SimClock start must be timezone-aware")
        self._validate_speed(speed)
        self._tz = tz
        self._seed = seed
        self._start = start.astimezone(UTC)
        self._real = real_monotonic
        self._speed = float(speed)
        self._sim_anchor = self._start
        self._real_anchor = self._real()
        self._paused = paused

    # ----------------------------------------------------------------- properties

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def start(self) -> datetime:
        return self._start

    # ----------------------------------------------------------------- reading time

    def now(self) -> datetime:
        if self._paused:
            return self._sim_anchor
        elapsed = (self._real() - self._real_anchor) * self._speed
        return self._sim_anchor + timedelta(seconds=elapsed)

    def local_now(self) -> datetime:
        return self.now().astimezone(self._tz)

    def monotonic(self) -> float:
        """Simulated seconds since the clock's start."""
        return (self.now() - self._start).total_seconds()

    def seconds_of_day(self) -> float:
        """Campus-local seconds since midnight (date-independent; use for scoping randomness)."""
        t = self.local_now()
        return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1e6

    # ----------------------------------------------------------------- control

    def _rebase(self) -> None:
        self._sim_anchor = self.now()
        self._real_anchor = self._real()

    @staticmethod
    def _validate_speed(speed: float) -> None:
        if speed not in ALLOWED_SIM_SPEEDS:
            raise ValueError(f"speed must be one of {ALLOWED_SIM_SPEEDS}, got {speed}")

    def set_speed(self, speed: float) -> None:
        self._validate_speed(speed)
        self._rebase()
        self._speed = float(speed)

    def pause(self) -> None:
        if not self._paused:
            self._rebase()
            self._paused = True

    def resume(self) -> None:
        if self._paused:
            self._real_anchor = self._real()
            self._paused = False

    def advance(self, seconds: float) -> None:
        """Jump forward instantly by ``seconds`` of sim time."""
        if seconds < 0:
            raise ValueError("cannot move simulated time backwards; use reset()")
        self._rebase()
        self._sim_anchor += timedelta(seconds=seconds)

    def fast_forward_to(self, target: dtime | datetime) -> None:
        """Jump to a campus-local time today (``dtime``) or an exact moment (``datetime``)."""
        if isinstance(target, datetime):
            if target.tzinfo is None:
                raise ValueError("target datetime must be timezone-aware")
            dest = target.astimezone(UTC)
        else:
            local_date = self.local_now().date()
            dest = datetime.combine(local_date, target, tzinfo=self._tz).astimezone(UTC)
        delta = (dest - self.now()).total_seconds()
        if delta < 0:
            raise ValueError("cannot fast-forward into the past; use reset()")
        self.advance(delta)

    def reset(self) -> None:
        """Back to the start time; speed and paused state are kept."""
        self._sim_anchor = self._start
        self._real_anchor = self._real()

    # ----------------------------------------------------------------- randomness / sleeping

    def rng(self, *scope: str) -> random.Random:
        """Independent deterministic random stream for ``scope``."""
        return random.Random(derive_seed(self._seed, *scope))

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds) / self._speed)


class ManualClock(SimClock):
    """A SimClock frozen in real time: only ``advance``/``fast_forward_to`` move it."""

    def __init__(self, start: datetime, *, seed: int = 42, tz: ZoneInfo = DEFAULT_TZ) -> None:
        super().__init__(start, speed=1, seed=seed, tz=tz, real_monotonic=lambda: 0.0)

    async def sleep(self, seconds: float) -> None:
        self.advance(max(0.0, seconds))
        await asyncio.sleep(0)
