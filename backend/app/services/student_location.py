"""Where the student is now — the location source for the commute decision (Feature 7).

There is NO real GPS yet. The only source is a clearly SYNTHETIC demo location:
a deterministic point near the student's assigned boarding stop (think "home /
hostel"), from ``derive_seed(SEED, "student-location", student_id)``. It never
moves and is always labelled ``source="synthetic"``. A phone-GPS source can
replace it later behind the same ``locate`` call. ``STUDENT_LOCATION_MODE=off``
disables it (→ LOCATION_UNAVAILABLE); the student is never assumed to be at the stop.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Literal

from app.core.clock import derive_seed
from app.core.config import Settings
from app.geo import LngLat
from app.geo.local_frame import LocalFrame
from app.models import Stop

SYNTHETIC_MIN_M = 60.0
"""Straight-line distance band of the synthetic location from the boarding stop."""
SYNTHETIC_MAX_M = 800.0


@dataclass(frozen=True)
class StudentLocation:
    point: LngLat
    source: Literal["synthetic"]
    label: str


class StudentLocationSource:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def locate(self, student_id: str, boarding_stop: Stop) -> StudentLocation | None:
        if self._settings.student_location_mode == "off":
            return None
        rng = random.Random(derive_seed(self._settings.seed, "student-location", student_id))
        bearing = rng.uniform(0.0, 2 * math.pi)
        dist = rng.uniform(SYNTHETIC_MIN_M, SYNTHETIC_MAX_M)
        lng, lat = boarding_stop.location.coordinates
        frame = LocalFrame((lng, lat))
        point = frame.to_lnglat(dist * math.sin(bearing), dist * math.cos(bearing))
        return StudentLocation(
            point=(round(point[0], 6), round(point[1], 6)),
            source="synthetic",
            label="Simulated location (demo, not GPS)",
        )
