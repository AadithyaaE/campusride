"""Geometry utilities.

Every coordinate in the backend is a ``(lng, lat)`` tuple — GeoJSON order.
Only the frontend map adapter converts to Leaflet's ``[lat, lng]``.

Routes are polylines with cumulative distances, so most questions
("where is the bus?", "has it passed the stop?", "how far to go?")
reduce to arithmetic on distances along the route.
"""

from app.geo.distance import EARTH_RADIUS_M, LngLat, bearing_deg, haversine_m, walking_distance_m
from app.geo.local_frame import LocalFrame
from app.geo.polyline import (
    PointOnLine,
    Polyline,
    bbox,
    cumulative_distances,
    interpolate_along,
    offset_polyline,
)
from app.geo.projection import (
    Projection,
    has_passed,
    project_point,
    project_point_windowed,
    remaining_distance,
    stop_distances,
)

__all__ = [
    "EARTH_RADIUS_M",
    "LngLat",
    "LocalFrame",
    "PointOnLine",
    "Polyline",
    "Projection",
    "bbox",
    "bearing_deg",
    "cumulative_distances",
    "has_passed",
    "haversine_m",
    "interpolate_along",
    "offset_polyline",
    "project_point",
    "project_point_windowed",
    "remaining_distance",
    "stop_distances",
    "walking_distance_m",
]
