"""Multi-bus comparison for a student's ASSIGNED boarding stop (Feature 6).

A deterministic decision-support layer — no ML, no new state. It orchestrates:

  Feature 4 matching   which buses serve the stop in the assigned direction,
                       distance / stops away / proximity / position
  Feature 5 ETA        eta, estimated arrival, traffic, confidence, delay factor
  tracked BusState     occupancy (synthetic, from the simulator's telemetry), delay

and adds only what is new: occupancy %, crowding band, an internal comparison
cost and the indicators FASTEST / LEAST_CROWDED / ASSIGNED / BEST_ALTERNATIVE.

Rules (all documented in docs/architecture.md, F6-*)
----------------------------------------------------
Options      buses whose Feature 5 status is ``predicted`` or ``at_stop``.
             ``passed`` / ``completed`` buses are EXCLUDED (not a useful future option).
Comparable   an option with live (non-stale) data that has not broken down.
             Stale / broken-down buses are still listed, but get no FASTEST /
             LEAST_CROWDED / BEST_ALTERNATIVE indicator.
Indicators   need at least two comparable options (with one bus there is nothing
             to compare). ASSIGNED always marks the college-assigned bus.
  FASTEST          lowest ETA seconds                       (tie → bus id)
  LEAST_CROWDED    lowest occupancy % (capacity known)      (tie → ETA, bus id)
  BEST_ALTERNATIVE the strongest option OTHER THAN the fastest bus: lowest
                   comparison cost among comparable, not-full buses except the
                   fastest (tie → ETA, bus id) — awarded only when that cost is at
                   most 15 min-equivalents above the fastest bus's cost. It may be
                   the assigned bus (when the assigned bus is not the fastest).
                   It is NOT "the second-fastest": a later, emptier bus wins over a
                   sooner, crowded one when the cost says so.
Cost         in minute-equivalents, LOWER is better, internal only (never shown):

    cost = ETA minutes
         + 0.20 min per occupancy point above 50 %         (92 % → +8.4)
         + 30 min if the bus is full (≥ 100 %)
         + 5 min if capacity is unknown (0)
         + 0.25 min per minute of reported delay (> 0)     (reliability risk)
         + 0 / 1 / 3 min for high / medium / low ETA confidence
         − 2 min for the college-assigned bus              (prefer the plan on a tie-ish)

The ETA already contains the expected lateness (Feature 5 ``delay_factor``); the
delay term here is a small reliability penalty, not a second ETA correction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Literal

from app.core.clock import Clock
from app.core.config import Settings
from app.models.common import BusStatus
from app.services.assignments import ResolvedAssignment
from app.services.capacity import available_seats as seats_available
from app.services.capacity import occupancy_percentage
from app.services.eta_service import EtaPrediction, EtaService
from app.services.matching import ServingBus
from app.services.tracking import is_stale

# ----------------------------------------------------------------- crowding bands
CROWDING_MEDIUM_FROM_PCT = 60
"""0–59 % Low · 60–79 % Medium · 80 %+ High (of the bus's seated capacity)."""
CROWDING_HIGH_FROM_PCT = 80

# ----------------------------------------------------------------- comparison cost
CROWDING_FREE_PCT = 50.0
CROWDING_COST_PER_PCT = 0.20
FULL_PENALTY_MIN = 30.0
UNKNOWN_CAPACITY_COST_MIN = 5.0
DELAY_COST_PER_MIN = 0.25
CONFIDENCE_COST_MIN = {"high": 0.0, "medium": 1.0, "low": 3.0}
ASSIGNED_BONUS_MIN = 2.0
ALTERNATIVE_MAX_EXTRA_COST_MIN = 15.0
MIN_COMPARABLE = 2

Crowding = Literal["Low", "Medium", "High", "Unknown"]
ExcludeReason = Literal["passed_stop", "trip_completed"]


class Indicator(StrEnum):
    ASSIGNED = "ASSIGNED"
    FASTEST = "FASTEST"
    LEAST_CROWDED = "LEAST_CROWDED"
    BEST_ALTERNATIVE = "BEST_ALTERNATIVE"


INDICATOR_ORDER = (
    Indicator.ASSIGNED,
    Indicator.FASTEST,
    Indicator.LEAST_CROWDED,
    Indicator.BEST_ALTERNATIVE,
)


# =========================================================================== pure rules


def crowding_level(pct: float | None) -> Crowding:
    if pct is None:
        return "Unknown"
    if pct >= CROWDING_HIGH_FROM_PCT:
        return "High"
    if pct >= CROWDING_MEDIUM_FROM_PCT:
        return "Medium"
    return "Low"


def delay_minutes(delay_s: int) -> int:
    """Whole minutes behind the timetable (negative = early), for display."""
    return round(delay_s / 60)


def comparison_cost(
    *, eta_s: float, pct: float | None, delay_s: int, confidence: str, assigned: bool
) -> float:
    """Internal decision-support cost in minute-equivalents (lower is better). Never shown."""
    cost = eta_s / 60.0
    if pct is None:
        cost += UNKNOWN_CAPACITY_COST_MIN
    else:
        cost += CROWDING_COST_PER_PCT * max(0.0, pct - CROWDING_FREE_PCT)
        if pct >= 100.0:
            cost += FULL_PENALTY_MIN
    cost += DELAY_COST_PER_MIN * max(0.0, delay_s / 60.0)
    cost += CONFIDENCE_COST_MIN.get(confidence, CONFIDENCE_COST_MIN["low"])
    if assigned:
        cost -= ASSIGNED_BONUS_MIN
    return round(cost, 4)


@dataclass(frozen=True)
class BusOption:
    sb: ServingBus
    prediction: EtaPrediction
    assigned: bool
    stale: bool
    occupancy_pct: float | None
    crowding: Crowding
    seats_available: int
    delay_minutes: int
    comparable: bool
    cost: float | None
    """Internal; None when the bus is not comparable."""
    indicators: tuple[Indicator, ...]
    trade_off: str | None
    """Plain-language difference to the fastest bus, e.g. "+3 min · 22 more seats free"."""

    @property
    def bus_id(self) -> str:
        return self.sb.bus.id

    @property
    def occupancy_percentage(self) -> int | None:
        return None if self.occupancy_pct is None else round(self.occupancy_pct)


@dataclass(frozen=True)
class ExcludedBus:
    sb: ServingBus
    reason: ExcludeReason


@dataclass(frozen=True)
class Comparison:
    options: list[BusOption]
    """Useful future options in arrival order (Feature 5 order) — NOT ranked by cost."""
    excluded: list[ExcludedBus]

    def with_indicator(self, indicator: Indicator) -> BusOption | None:
        return next((o for o in self.options if indicator in o.indicators), None)


def _trade_off(o_eta_min: int, o_seats: int, fastest: BusOption) -> str:
    assert fastest.prediction.eta_minutes is not None
    dt = o_eta_min - fastest.prediction.eta_minutes
    parts = [f"+{dt} min vs {fastest.bus_id}" if dt > 0 else f"Same time as {fastest.bus_id}"]
    ds = o_seats - fastest.seats_available
    if ds != 0:
        parts.append(f"{abs(ds)} {'more' if ds > 0 else 'fewer'} seat{'s' if abs(ds) != 1 else ''} free")
    return " · ".join(parts)


def compare(
    arrivals: list[tuple[ServingBus, EtaPrediction]],
    *,
    assigned_bus_id: str | None,
    now: datetime,
    stale_after_s: float,
) -> Comparison:
    """Compare the buses serving one stop. ``arrivals`` come from Feature 5 (already in ETA order)."""
    excluded: list[ExcludedBus] = []
    drafts: list[dict] = []
    for sb, p in arrivals:
        if p.status == "passed":
            excluded.append(ExcludedBus(sb, "passed_stop"))
            continue
        if p.status == "completed":
            excluded.append(ExcludedBus(sb, "trip_completed"))
            continue
        s = sb.state
        assigned = sb.bus.id == assigned_bus_id
        stale = is_stale(s, now, stale_after_s)
        pct = occupancy_percentage(s.occupancy, sb.bus.capacity)
        has_eta = p.eta_s is not None and math.isfinite(p.eta_s)
        comparable = has_eta and not stale and s.status is not BusStatus.BREAKDOWN
        drafts.append(
            {
                "sb": sb,
                "prediction": p,
                "assigned": assigned,
                "stale": stale,
                "occupancy_pct": pct,
                "crowding": crowding_level(pct),
                "seats_available": seats_available(s.occupancy, sb.bus.capacity),
                "delay_minutes": delay_minutes(s.delay_s),
                "comparable": comparable,
                "cost": (
                    comparison_cost(
                        eta_s=p.eta_s or 0.0,
                        pct=pct,
                        delay_s=s.delay_s,
                        confidence=p.confidence,
                        assigned=assigned,
                    )
                    if comparable
                    else None
                ),
            }
        )

    comparable = [d for d in drafts if d["comparable"]]
    picks: dict[Indicator, str] = {}
    if len(comparable) >= MIN_COMPARABLE:

        def eta_of(d: dict) -> float:
            return d["prediction"].eta_s

        picks[Indicator.FASTEST] = min(comparable, key=lambda d: (eta_of(d), d["sb"].bus.id))["sb"].bus.id
        known = [d for d in comparable if d["occupancy_pct"] is not None]
        if known:
            picks[Indicator.LEAST_CROWDED] = min(
                known, key=lambda d: (d["occupancy_pct"], eta_of(d), d["sb"].bus.id)
            )["sb"].bus.id
        fastest = next(d for d in comparable if d["sb"].bus.id == picks[Indicator.FASTEST])
        others = [
            d
            for d in comparable
            if d is not fastest and (d["occupancy_pct"] is None or d["occupancy_pct"] < 100.0)
        ]
        if others:
            best = min(others, key=lambda d: (d["cost"], eta_of(d), d["sb"].bus.id))
            if best["cost"] <= fastest["cost"] + ALTERNATIVE_MAX_EXTRA_COST_MIN:
                picks[Indicator.BEST_ALTERNATIVE] = best["sb"].bus.id

    def indicators_for(d: dict) -> tuple[Indicator, ...]:
        bus_id = d["sb"].bus.id
        found = {i for i, b in picks.items() if b == bus_id}
        if d["assigned"]:
            found.add(Indicator.ASSIGNED)
        return tuple(i for i in INDICATOR_ORDER if i in found)

    options = [BusOption(**d, indicators=indicators_for(d), trade_off=None) for d in drafts]
    fastest = next((o for o in options if Indicator.FASTEST in o.indicators), None)
    if fastest is not None:
        options = [
            o
            if not o.comparable or o is fastest or o.prediction.eta_minutes is None
            else replace(o, trade_off=_trade_off(o.prediction.eta_minutes, o.seats_available, fastest))
            for o in options
        ]
    return Comparison(options=options, excluded=excluded)


# =========================================================================== service


@dataclass(frozen=True)
class StudentBusOptions:
    assignment: ResolvedAssignment
    my_bus: tuple[ServingBus, EtaPrediction | None] | None
    """As Feature 5 returns it: None = no live state; prediction None = not serving the stop."""
    comparison: Comparison
    computed_at: datetime

    @property
    def assigned_option(self) -> BusOption | None:
        return next((o for o in self.comparison.options if o.assigned), None)


class BusComparisonService:
    """Orchestrates Feature 5 arrivals (which use Feature 4 matching) into a comparison."""

    def __init__(self, eta: EtaService, settings: Settings, clock: Clock) -> None:
        self._eta = eta
        self._settings = settings
        self._clock = clock

    async def for_student(self, student_id: str) -> StudentBusOptions | None:
        """Options at the student's ASSIGNED boarding stop and direction; None if unassigned."""
        arrivals = await self._eta.student_arrivals(student_id)
        if arrivals is None:
            return None
        now = self._clock.now()
        comparison = compare(
            arrivals.arrivals,
            assigned_bus_id=arrivals.assignment.bus.id,
            now=now,
            stale_after_s=self._settings.bus_stale_after_s,
        )
        return StudentBusOptions(
            assignment=arrivals.assignment,
            my_bus=arrivals.my_bus,
            comparison=comparison,
            computed_at=now,
        )
