"""Ridership ledger (Feature 13): the peak on-board load of every trip, for "passengers today".

Telemetry stores positions, not headcounts, and ``BusState`` only holds the CURRENT
occupancy. The ledger listens to ``BusStateUpdated`` (published by the ONE ingest
pipeline) and remembers, per trip, the highest Feature 8 occupancy seen while the bus
was running (en route / dwelling / deviated / breakdown). It computes nothing new:

    passengers carried by a trip = max(BusState.occupancy) during the trip

* TO_CAMPUS riders accumulate until campus → the peak is everyone who rode.
* FROM_CAMPUS riders board at campus and alight along the way → the peak is the
  load at departure.

The ledger is in memory: a simulator reset (the clock goes back) starts a trip over,
and a backend restart starts empty (the simulator resets on start-up anyway).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models.common import BusStatus
from app.models.events import BusStateUpdated

RUNNING = (BusStatus.EN_ROUTE, BusStatus.DWELLING, BusStatus.DEVIATED, BusStatus.BREAKDOWN)


@dataclass
class TripLoad:
    trip_id: str
    bus_id: str
    route_id: str | None
    peak: int
    last_ts: datetime


class RidershipLedger:
    def __init__(self) -> None:
        self._trips: dict[str, TripLoad] = {}

    async def on_bus_state(self, event: BusStateUpdated) -> None:
        s = event.state
        if s.trip_id is None:
            return
        entry = self._trips.get(s.trip_id)
        if entry is not None and s.ts < entry.last_ts:
            entry = None  # the clock went back (simulator reset): the trip starts over
        if entry is None:
            entry = TripLoad(s.trip_id, s.id, s.route_id, 0, s.ts)
            self._trips[s.trip_id] = entry
        entry.last_ts = s.ts
        if s.status in RUNNING:
            entry.peak = max(entry.peak, s.occupancy)

    def peak(self, trip_id: str) -> int:
        entry = self._trips.get(trip_id)
        return entry.peak if entry else 0

    def clear(self) -> None:
        self._trips.clear()
