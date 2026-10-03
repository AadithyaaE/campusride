"""Great-circle distance and bearing on (lng, lat) points."""

from __future__ import annotations

import math

LngLat = tuple[float, float]
"""A coordinate in GeoJSON order: (longitude, latitude), degrees."""

EARTH_RADIUS_M = 6_371_008.8  # mean Earth radius (IUGG)

DEFAULT_WALK_DETOUR = 1.3
"""Straight-line → street-network walking distance factor."""


def haversine_m(a: LngLat, b: LngLat) -> float:
    """Great-circle distance in metres between two (lng, lat) points."""
    lng1, lat1 = math.radians(a[0]), math.radians(a[1])
    lng2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a: LngLat, b: LngLat) -> float:
    """Initial compass bearing from ``a`` to ``b`` in degrees [0, 360)."""
    lng1, lat1 = math.radians(a[0]), math.radians(a[1])
    lng2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlng = lng2 - lng1
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def walking_distance_m(a: LngLat, b: LngLat, detour: float = DEFAULT_WALK_DETOUR) -> float:
    """Estimated walking distance: straight line × street-network detour factor."""
    if detour < 1.0:
        raise ValueError("detour factor must be >= 1.0")
    return haversine_m(a, b) * detour
