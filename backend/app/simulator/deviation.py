"""Demo route deviation for SYNTHETIC buses (Feature 10).

The route remains the planned route; demo deviation changes the synthetic bus
position, not the route geometry. The simulator moves the ground-truth point a
fixed distance perpendicular to the direction of travel; the result then goes
through the normal telemetry → tracking pipeline like any other fix.
"""

from __future__ import annotations

import math
from typing import Literal

from app.geo import LngLat, LocalFrame, project_point
from app.geo.polyline import Polyline

DeviationMode = Literal["normal", "minor", "major"]
MODES: tuple[DeviationMode, ...] = ("normal", "minor", "major")


def offset_point(p: LngLat, heading_deg: float, offset_m: float, line: Polyline) -> LngLat:
    """``p`` moved ``offset_m`` perpendicular to ``heading_deg`` (compass degrees).

    Of the two sides, the one FARTHER from the planned route is used (deterministic),
    so a route that doubles back nearby can't hide the deviation.
    """
    if offset_m <= 0:
        return p
    h = math.radians(heading_deg)
    left = (-math.cos(h), math.sin(h))  # east/north components of the left-hand normal
    frame = LocalFrame(p)
    candidates = [
        frame.to_lnglat(left[0] * offset_m * side, left[1] * offset_m * side) for side in (1.0, -1.0)
    ]
    dist = [project_point(line.coords, line.cum, c).offset_m for c in candidates]
    return candidates[0] if dist[0] >= dist[1] else candidates[1]
