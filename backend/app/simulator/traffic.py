"""Synthetic driving speed: road class × time-of-day traffic × per-bus driver factor."""

from __future__ import annotations

from app.models import TrafficProfile
from app.models.common import SegmentClass

MIN_SPEED_MPS = 2.0  # never crawl below this in the model (avoids huge leg times)


class TrafficModel:
    def __init__(self, profiles: list[TrafficProfile]) -> None:
        self._profiles = {SegmentClass(p.id): p for p in profiles}
        missing = set(SegmentClass) - set(self._profiles)
        if missing:
            raise ValueError(f"traffic profiles missing for {sorted(m.value for m in missing)}")

    def speed_mps(self, segment_class: SegmentClass, seconds_of_day: float, driver_factor: float) -> float:
        p = self._profiles[segment_class]
        return max(MIN_SPEED_MPS, p.free_flow_mps * p.factor_at(seconds_of_day) * driver_factor)
