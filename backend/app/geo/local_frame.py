"""Flat east/north metre frame around an origin (equirectangular projection).

Accurate to well under 1 % within ~30 km of the origin, which covers a
city-scale bus network. Used for projection maths, where planar vector
algebra is far simpler than spherical geometry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.geo.distance import EARTH_RADIUS_M, LngLat


@dataclass(frozen=True)
class LocalFrame:
    origin: LngLat
    _cos_lat: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_cos_lat", math.cos(math.radians(self.origin[1])))

    def to_xy(self, p: LngLat) -> tuple[float, float]:
        """(lng, lat) → (east_m, north_m) relative to the origin."""
        x = math.radians(p[0] - self.origin[0]) * EARTH_RADIUS_M * self._cos_lat
        y = math.radians(p[1] - self.origin[1]) * EARTH_RADIUS_M
        return x, y

    def to_lnglat(self, x: float, y: float) -> LngLat:
        """(east_m, north_m) relative to the origin → (lng, lat)."""
        lng = self.origin[0] + math.degrees(x / (EARTH_RADIUS_M * self._cos_lat))
        lat = self.origin[1] + math.degrees(y / EARTH_RADIUS_M)
        return lng, lat
