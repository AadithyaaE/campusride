"""Deterministic per-bus motion model (pure; no I/O, no wall clock).

For each scheduled trip a bus gets a TIMELINE of legs, built once:

    [pre-departure at stop 0] → travel 0→1 → dwell@1 → travel 1→2 → … → arrive final stop

* travel legs: duration = Σ piece_length / speed(road class, time of day, driver factor)
  over the real route geometry; position moves at constant speed within a leg,
  so movement is continuous (no teleporting).
* dwell legs: the route's ``dwell_s`` per stop, plus an optional seeded "hold"
  (a deterministic delay) at one intermediate stop.
* stop 0 is the departure point: the bus waits there until the scheduled start
  (it is never reported as having "passed" its first stop early).

``BusPlan.at(t)`` answers "where is the bus at sim time t?" by lookup — the same
inputs always give the same answer. Randomness comes only from
``derive_seed(SEED, scope…)`` with date-free scopes (bus id, variant, time of day).
"""

from __future__ import annotations

import bisect
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.core.clock import derive_seed
from app.geo import LngLat, Polyline
from app.models import Bus, Route, RouteDirection, Trip
from app.simulator.passengers import occupancy_profile
from app.simulator.traffic import TrafficModel

PRE_TRIP_WINDOW_S = 15 * 60
"""A bus reports its next trip (waiting at stop 0) this long before departure."""

DRIVER_FACTOR_RANGE = (0.88, 1.12)
HOLD_PROBABILITY = 0.4
HOLD_RANGE_S = (120.0, 420.0)

Phase = Literal["pre", "dwell", "move", "done"]


@dataclass(frozen=True)
class Leg:
    t0: float  # seconds after the trip's scheduled start
    t1: float
    d0: float  # distance along the route direction (m)
    d1: float
    stop_seq: int | None = None  # set for dwell legs


@dataclass(frozen=True)
class AgentState:
    """Ground truth inside the simulator (never exposed to intelligence modules)."""

    trip_id: str
    phase: Phase
    distance_m: float
    lnglat: LngLat
    speed_mps: float
    heading_deg: float
    stop_seq: int | None  # stop at (dwell/pre/done) or last departed (move)
    occupancy: int


def rng_for(seed: int, *scope: str) -> random.Random:
    return random.Random(derive_seed(seed, *scope))


def driver_factor(seed: int, bus_id: str) -> float:
    return rng_for(seed, "bus", bus_id, "driver").uniform(*DRIVER_FACTOR_RANGE)


@dataclass
class TripPlan:
    trip: Trip
    route: Route
    variant: RouteDirection
    line: Polyline
    legs: list[Leg]
    occupancy_after: list[int]
    hold: tuple[int, float] | None
    _starts: list[float] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._starts = [leg.t0 for leg in self.legs]

    @property
    def start(self) -> datetime:
        return self.trip.scheduled_start

    @property
    def duration_s(self) -> float:
        return self.legs[-1].t1 if self.legs else 0.0

    def stop_distance(self, seq: int) -> float:
        return self.variant.stops[seq].distance_along_m

    def at(self, when: datetime) -> AgentState:
        off = (when - self.start).total_seconds()
        n = len(self.variant.stops)
        if off < 0 or not self.legs:
            return self._state("pre", self.stop_distance(0), 0.0, 0)
        if off >= self.duration_s:
            return self._state("done", self.stop_distance(n - 1), 0.0, n - 1)
        leg = self.legs[bisect.bisect_right(self._starts, off) - 1]
        if leg.stop_seq is not None:
            return self._state("dwell", leg.d0, 0.0, leg.stop_seq)
        frac = (off - leg.t0) / (leg.t1 - leg.t0)
        d = leg.d0 + frac * (leg.d1 - leg.d0)
        speed = (leg.d1 - leg.d0) / (leg.t1 - leg.t0)
        departed = max(s.seq for s in self.variant.stops if s.distance_along_m <= leg.d0 + 1e-6)
        return self._state("move", d, speed, departed)

    def _state(self, phase: Phase, d: float, speed: float, seq: int) -> AgentState:
        p = self.line.interpolate(d)
        return AgentState(
            trip_id=self.trip.id,
            phase=phase,
            distance_m=d,
            lnglat=p.point,
            speed_mps=speed,
            heading_deg=round(p.heading_deg, 1),
            stop_seq=seq,
            occupancy=self.occupancy_after[seq] if phase != "pre" else self.occupancy_after[0],
        )


def build_trip_plan(
    trip: Trip,
    route: Route,
    bus: Bus,
    traffic: TrafficModel,
    *,
    seed: int,
    tz: ZoneInfo,
) -> TripPlan:
    variant = route.variant(trip.variant_id)
    line = route.polyline(variant.direction)
    stops = variant.stops
    factor = driver_factor(seed, bus.id)
    tod_key = trip.scheduled_start.astimezone(tz).strftime("%H%M")  # date-free scope

    hold_rng = rng_for(seed, "bus", bus.id, variant.variant_id, tod_key, "hold")
    hold: tuple[int, float] | None = None
    if len(stops) > 2 and hold_rng.random() < HOLD_PROBABILITY:
        hold = (hold_rng.randint(1, len(stops) - 2), round(hold_rng.uniform(*HOLD_RANGE_S)))

    def seconds_of_day(offset_s: float) -> float:
        t = (trip.scheduled_start + timedelta(seconds=offset_s)).astimezone(tz)
        return t.hour * 3600 + t.minute * 60 + t.second

    def travel_time(d0: float, d1: float, offset_s: float) -> float:
        tod = seconds_of_day(offset_s)
        total = 0.0
        coords_cum = line.cum
        for j in range(len(coords_cum) - 1):
            a, b = max(d0, coords_cum[j]), min(d1, coords_cum[j + 1])
            if b <= a:
                continue
            cls = route.segment_class_at((a + b) / 2, variant.direction)
            total += (b - a) / traffic.speed_mps(cls, tod, factor)
        return max(total, 1.0)

    legs: list[Leg] = []
    t = 0.0
    for k, rs in enumerate(stops):
        if k > 0:
            prev = stops[k - 1].distance_along_m
            dur = travel_time(prev, rs.distance_along_m, t)
            legs.append(Leg(t, t + dur, prev, rs.distance_along_m))
            t += dur
        if k < len(stops) - 1:
            dwell = (0.0 if k == 0 else float(rs.dwell_s)) + (hold[1] if hold and hold[0] == k else 0.0)
            if dwell > 0:
                legs.append(Leg(t, t + dwell, rs.distance_along_m, rs.distance_along_m, k))
                t += dwell

    occ_rng = rng_for(seed, "bus", bus.id, variant.variant_id, tod_key, "occupancy")
    occupancy = occupancy_profile(occ_rng, len(stops), bus.capacity, variant.direction)
    return TripPlan(
        trip=trip, route=route, variant=variant, line=line, legs=legs, occupancy_after=occupancy, hold=hold
    )


@dataclass
class BusPlan:
    """All of one bus's trips for the service day, ordered by departure."""

    bus: Bus
    trips: list[TripPlan]

    def plan_at(self, when: datetime) -> TripPlan | None:
        if not self.trips:
            return None
        current = self.trips[0]
        for tp in self.trips:
            if (when - tp.start).total_seconds() >= -PRE_TRIP_WINDOW_S:
                current = tp
        return current

    def at(self, when: datetime) -> AgentState | None:
        tp = self.plan_at(when)
        return tp.at(when) if tp else None
