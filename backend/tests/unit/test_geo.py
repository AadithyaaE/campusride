"""Geometry: distance, local frame, polyline interpolation/projection, linear referencing."""

from __future__ import annotations

import math

import pytest

from app.geo import (
    LocalFrame,
    Polyline,
    bbox,
    bearing_deg,
    cumulative_distances,
    has_passed,
    haversine_m,
    offset_polyline,
    project_point,
    project_point_windowed,
    remaining_distance,
    stop_distances,
    walking_distance_m,
)

CHENNAI = (80.20921, 12.90498)  # (lng, lat) — the synthetic campus
FRAME = LocalFrame(CHENNAI)


def xy_line(*pts: tuple[float, float]) -> Polyline:
    """Build a polyline from local metre coordinates around the campus."""
    return Polyline.from_coords([FRAME.to_lnglat(x, y) for x, y in pts])


# --------------------------------------------------------------------------- distance


def test_haversine_one_degree_of_latitude():
    assert haversine_m((80.0, 12.0), (80.0, 13.0)) == pytest.approx(111_195, rel=1e-3)


def test_haversine_zero_and_symmetric():
    a, b = (80.1, 12.9), (80.25, 13.0)
    assert haversine_m(a, a) == 0
    assert haversine_m(a, b) == pytest.approx(haversine_m(b, a))


def test_coordinates_are_lng_lat_order():
    # Moving 0.01° in *longitude* at 13°N is shorter than 0.01° in latitude.
    d_lng = haversine_m((80.20, 12.90), (80.21, 12.90))
    d_lat = haversine_m((80.20, 12.90), (80.20, 12.91))
    assert d_lng == pytest.approx(d_lat * math.cos(math.radians(12.9)), rel=1e-3)


def test_bearing_cardinal_directions():
    o = CHENNAI
    assert bearing_deg(o, FRAME.to_lnglat(0, 100)) == pytest.approx(0, abs=0.01)
    assert bearing_deg(o, FRAME.to_lnglat(100, 0)) == pytest.approx(90, abs=0.01)
    assert bearing_deg(o, FRAME.to_lnglat(0, -100)) == pytest.approx(180, abs=0.01)
    assert bearing_deg(o, FRAME.to_lnglat(-100, 0)) == pytest.approx(270, abs=0.01)


def test_walking_distance_applies_detour():
    a, b = CHENNAI, FRAME.to_lnglat(300, 400)
    assert walking_distance_m(a, b) == pytest.approx(500 * 1.3, rel=1e-3)
    with pytest.raises(ValueError):
        walking_distance_m(a, b, detour=0.9)


# --------------------------------------------------------------------------- local frame


def test_local_frame_round_trip_and_scale():
    p = (80.25, 12.95)
    x, y = FRAME.to_xy(p)
    back = FRAME.to_lnglat(x, y)
    assert back == pytest.approx(p, abs=1e-9)
    assert math.hypot(x, y) == pytest.approx(haversine_m(CHENNAI, p), rel=5e-3)


# --------------------------------------------------------------------------- polyline

L_SHAPE = ((0, 0), (1000, 0), (1000, 1000))  # east 1 km, then north 1 km


def test_cumulative_distances():
    line = xy_line(*L_SHAPE)
    assert line.cum[0] == 0
    assert line.cum[1] == pytest.approx(1000, abs=1)
    assert line.length_m == pytest.approx(2000, abs=2)
    assert cumulative_distances([]) == []


def test_interpolate_positions_and_headings():
    line = xy_line(*L_SHAPE)
    mid_first = line.interpolate(500)
    assert FRAME.to_xy(mid_first.point) == pytest.approx((500, 0), abs=0.5)
    assert mid_first.heading_deg == pytest.approx(90, abs=0.1)
    on_second = line.interpolate(line.cum[1] + 500)
    assert FRAME.to_xy(on_second.point) == pytest.approx((1000, 500), abs=0.5)
    assert on_second.heading_deg == pytest.approx(0, abs=0.1)
    assert on_second.segment_index == 1


def test_interpolate_clamps_to_ends():
    line = xy_line(*L_SHAPE)
    assert line.interpolate(-50).point == line.coords[0]
    assert line.interpolate(1e9).point == pytest.approx(line.coords[-1])


def test_project_point_distance_and_offset():
    line = xy_line(*L_SHAPE)
    p = line.project(FRAME.to_lnglat(500, 30))
    assert p.distance_along_m == pytest.approx(500, abs=0.5)
    assert p.offset_m == pytest.approx(30, abs=0.2)
    assert p.segment_index == 0
    q = line.project(FRAME.to_lnglat(1200, 500))
    assert q.distance_along_m == pytest.approx(line.cum[1] + 500, abs=0.5)
    assert q.offset_m == pytest.approx(200, abs=0.5)


def test_interpolate_project_round_trip():
    line = xy_line(*L_SHAPE)
    for d in [0, 1, 250, 999, 1000, 1001, 1500, line.length_m]:
        p = line.interpolate(d).point
        proj = line.project(p)
        assert proj.distance_along_m == pytest.approx(d, abs=0.05)
        assert proj.offset_m < 0.05


def test_reversed_polyline_distance_relation_is_exact():
    line = xy_line(*L_SHAPE)
    rev = line.reversed()
    assert rev.coords[0] == line.coords[-1]
    assert rev.cum[0] == 0
    assert rev.length_m == line.length_m
    for d in (0, 300, 1500, line.length_m):
        pt = line.interpolate(d).point
        assert rev.project(pt).distance_along_m == pytest.approx(line.length_m - d, abs=0.05)


def test_slice():
    line = xy_line(*L_SHAPE)
    part = line.slice(500, line.cum[1] + 500)
    assert part.length_m == pytest.approx(1000, abs=1)
    assert FRAME.to_xy(part.coords[0]) == pytest.approx((500, 0), abs=0.5)
    with pytest.raises(ValueError):
        line.slice(10, 5)


def test_offset_polyline_departs_and_rejoins():
    line = xy_line((0, 0), (2000, 0))  # due east
    detour = offset_polyline(line.coords, line.cum, 500, 1500, offset_m=200)
    xs = [FRAME.to_xy(p) for p in detour]
    assert xs[0] == pytest.approx((500, 0), abs=0.5)  # leaves the route
    assert xs[-1] == pytest.approx((1500, 0), abs=0.5)  # rejoins it
    peak = max(y for _, y in xs)
    assert peak == pytest.approx(200, abs=1)  # positive offset = left of travel = north


def test_bbox():
    assert bbox([(1, 5), (3, 2), (2, 9)]) == (1, 2, 3, 9)
    with pytest.raises(ValueError):
        bbox([])


# --------------------------------------------------------------------------- linear referencing

OUT_AND_BACK = ((0, 0), (1000, 0), (1000, 12), (0, 12))  # return leg 12 m north


def test_windowed_projection_picks_the_right_pass():
    line = xy_line(*OUT_AND_BACK)
    p = FRAME.to_lnglat(300, 6)  # equidistant from both passes
    outbound = project_point_windowed(line.coords, line.cum, p, hint_d=300)
    assert outbound.distance_along_m == pytest.approx(300, abs=1)
    return_d = line.cum[2] + 700
    inbound = project_point_windowed(line.coords, line.cum, p, hint_d=return_d)
    assert inbound.distance_along_m == pytest.approx(return_d, abs=1)


def test_stop_distances_are_monotonic_on_revisited_road():
    line = xy_line(*OUT_AND_BACK)
    stops = [FRAME.to_lnglat(300, 0), FRAME.to_lnglat(300, 12)]
    first, second = stop_distances(line.coords, line.cum, stops)
    assert first.distance_along_m == pytest.approx(300, abs=1)
    assert second.distance_along_m == pytest.approx(line.cum[2] + 700, abs=1)


def test_stop_distances_rejects_far_stop():
    line = xy_line(*L_SHAPE)
    with pytest.raises(ValueError, match="off the route"):
        stop_distances(line.coords, line.cum, [FRAME.to_lnglat(500, 120)], max_offset_m=50)


def test_project_point_validates_input():
    with pytest.raises(ValueError):
        project_point([CHENNAI], [0.0], CHENNAI)


@pytest.mark.parametrize(
    ("bus", "stop", "passed"),
    [(100, 500, False), (500, 500, False), (514, 500, False), (516, 500, True)],
)
def test_has_passed_uses_tolerance(bus, stop, passed):
    assert has_passed(bus, stop) is passed


def test_remaining_distance():
    assert remaining_distance(200, 500) == 300
    assert remaining_distance(600, 500) == 0
