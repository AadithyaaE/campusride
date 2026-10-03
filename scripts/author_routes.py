"""One-time route authoring: OSRM road geometry → committed GeoJSON seed files.

    python scripts/author_routes.py            # fetch (or reuse cache), write seed files
    python scripts/author_routes.py --check    # report only, write nothing

Reads ``scripts/route_spec.json`` (fictional campus, stops and routes placed
on the real Chennai road network) and writes:

    backend/data/seed/stops.geojson
    backend/data/seed/routes.geojson

This is the ONLY part of CampusRide that talks to an external routing
service, and only at authoring time. The application, simulator and tests
read the committed GeoJSON and work fully offline.

Pipeline per route:
  1. OSRM /route through the route's anchor waypoints (geometry + per-segment speeds)
  2. classify each segment (highway / arterial / local) from OSRM's speed
  3. remove "spurs" — out-and-back loops OSRM adds when a waypoint sits on a
     divided road or junction
  4. snap stops onto the geometry in order; a stop shared by several routes
     gets one canonical location that must lie on every route serving it

Route data © OpenStreetMap contributors (ODbL), routed with OSRM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.geo import LngLat, Polyline, haversine_m, stop_distances  # noqa: E402

SPEC_PATH = ROOT / "scripts" / "route_spec.json"
CACHE_DIR = ROOT / "scripts" / ".osrm_cache"
OUT_DIR = ROOT / "backend" / "data" / "seed"
USER_AGENT = "CampusRide-route-authoring/0.1 (SIH prototype; one-time authoring)"

# OSRM's demo car profile reports ~18 m/s for trunk and primary roads alike, so
# speed only separates arterial from local roads. Highways (OMR, ECR) are
# declared explicitly per route in the spec as "highway_spans" between stops.
ARTERIAL_MIN_MPS = 13.0  # ≈47 km/h; residential / unclassified roads report ~9–11 m/s
MIN_CLASS_RUN_M = 150.0  # shorter class runs are merged into their neighbour

SPUR_RADIUS_M = 40.0  # path returns within this distance of an earlier point …
SPUR_MIN_LOOP_M = 60.0  # … after travelling at least this far …
SPUR_MAX_LOOP_M = 2_500.0  # … but no further than this → it was a spur

SHARED_STOP_MAX_OFFSET_M = 50.0  # canonical shared-stop location vs. each route
ENDPOINT_MAX_OFFSET_M = 30.0
APPROX_WARN_OFFSET_M = 250.0


# --------------------------------------------------------------------------- OSRM


def fetch_route(base_url: str, waypoints: list[LngLat]) -> dict:
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lng, lat in waypoints)
    url = (
        f"{base_url}/route/v1/driving/{coords}"
        "?overview=full&geometries=geojson&annotations=speed,distance&continue_straight=true"
    )
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error for {url}: {data.get('code')} {data.get('message')}")
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    time.sleep(1.1)  # be polite to the public demo server (≤1 req/s)
    return data


# --------------------------------------------------------------------------- geometry clean-up


def classify(speed_mps: float) -> str:
    return "arterial" if speed_mps >= ARTERIAL_MIN_MPS else "local"


def apply_highway_spans(line: Polyline, classes: list[str], spans: list[tuple[float, float]]) -> list[str]:
    out = list(classes)
    for i in range(len(out)):
        mid = (line.cum[i] + line.cum[i + 1]) / 2
        if any(lo <= mid <= hi for lo, hi in spans):
            out[i] = "highway"
    return out


def osrm_geometry(route: dict) -> tuple[list[LngLat], list[str]]:
    coords: list[LngLat] = [(c[0], c[1]) for c in route["geometry"]["coordinates"]]
    speeds: list[float] = []
    for leg in route["legs"]:
        speeds.extend(leg["annotation"]["speed"])
    if len(speeds) != len(coords) - 1:
        raise RuntimeError(f"annotation/geometry mismatch: {len(speeds)} speeds, {len(coords)} points")
    return coords, [classify(s) for s in speeds]


def dedupe(coords: list[LngLat], classes: list[str]) -> tuple[list[LngLat], list[str]]:
    out_c, out_k = [coords[0]], []
    for p, k in zip(coords[1:], classes):
        if haversine_m(out_c[-1], p) < 0.05:
            continue
        out_c.append(p)
        out_k.append(k)
    return out_c, out_k


def remove_spurs(coords: list[LngLat], classes: list[str]) -> tuple[list[LngLat], list[str], int]:
    """Cut out-and-back loops: if the path comes back within SPUR_RADIUS_M of an
    earlier point after a short excursion, jump straight across."""
    cum = [0.0]
    for a, b in zip(coords, coords[1:]):
        cum.append(cum[-1] + haversine_m(a, b))

    out_c, out_k, removed = [coords[0]], [], 0
    i, n = 0, len(coords)
    while i < n - 1:
        best = None
        j = i + 2
        while j < n and cum[j] - cum[i] <= SPUR_MAX_LOOP_M:
            if cum[j] - cum[i] >= SPUR_MIN_LOOP_M and haversine_m(coords[i], coords[j]) <= SPUR_RADIUS_M:
                best = j
            j += 1
        nxt = best if best is not None else i + 1
        if best is not None:
            removed += 1
        out_c.append(coords[nxt])
        out_k.append(classes[i])
        i = nxt
    return out_c, out_k, removed


def smooth_classes(coords: list[LngLat], classes: list[str]) -> list[str]:
    """Merge class runs shorter than MIN_CLASS_RUN_M into the preceding run."""
    seg_len = [haversine_m(a, b) for a, b in zip(coords, coords[1:])]
    out = list(classes)
    changed = True
    while changed:
        changed = False
        runs = rle(out)
        idx = 0
        for r, (k, count) in enumerate(runs):
            length = sum(seg_len[idx : idx + count])
            if length < MIN_CLASS_RUN_M and len(runs) > 1:
                neighbour = runs[r - 1][0] if r > 0 else runs[r + 1][0]
                if neighbour != k:
                    out[idx : idx + count] = [neighbour] * count
                    changed = True
                    break
            idx += count
    return out


def rle(values: list[str]) -> list[list]:
    runs: list[list] = []
    for v in values:
        if runs and runs[-1][0] == v:
            runs[-1][1] += 1
        else:
            runs.append([v, 1])
    return runs


# --------------------------------------------------------------------------- main


def author(spec: dict) -> tuple[dict, dict, list[str]]:
    stops_spec: dict = spec["stops"]
    anchors: dict = spec["anchors"]
    canonical: dict[str, LngLat] = {}
    usage: dict[str, list[str]] = {sid: [] for sid in stops_spec}
    problems: list[str] = []
    route_features = []

    def point_of(ref: str) -> LngLat:
        if ref in anchors:
            return tuple(anchors[ref])  # type: ignore[return-value]
        return tuple(stops_spec[ref]["approx"])  # type: ignore[return-value]

    for rs in spec["routes"]:
        rid = rs["id"]
        data = fetch_route(spec["osrm_base_url"], [point_of(w) for w in rs["waypoints"]])
        coords, classes = osrm_geometry(data["routes"][0])
        coords, classes = dedupe(coords, classes)
        coords, classes, spurs = remove_spurs(coords, classes)
        coords, classes = dedupe(coords, classes)
        classes = smooth_classes(coords, classes)
        line = Polyline.from_coords(coords)

        targets = [canonical.get(sid, point_of(sid)) for sid in rs["stops"]]
        projections = stop_distances(line.coords, line.cum, targets)
        at = {sid: p.distance_along_m for sid, p in zip(rs["stops"], projections)}
        classes = apply_highway_spans(line, classes, [(at[a], at[b]) for a, b in rs.get("highway_spans", [])])

        print(
            f"\n== {rid} {rs['name']}: {line.length_m / 1000:.2f} km, "
            f"{len(coords)} pts, spurs removed: {spurs}, classes: "
            + ", ".join(
                f"{k} {sum(c for kk, c in rle(classes) if kk == k)}" for k in ("highway", "arterial", "local")
            )
        )

        for idx, (sid, proj) in enumerate(zip(rs["stops"], projections)):
            usage[sid].append(rid)
            is_endpoint = idx in (0, len(rs["stops"]) - 1)
            tag = ""
            if sid in canonical:
                tag = "shared"
                if proj.offset_m > SHARED_STOP_MAX_OFFSET_M:
                    problems.append(f"{rid}: shared stop {sid} is {proj.offset_m:.0f} m off this route")
            else:
                canonical[sid] = (
                    line.coords[0] if idx == 0 else line.coords[-1] if is_endpoint else proj.snapped
                )
                if proj.offset_m > APPROX_WARN_OFFSET_M:
                    tag = "WARN approx far from road"
            if is_endpoint:
                end_gap = proj.distance_along_m if idx == 0 else line.length_m - proj.distance_along_m
                if end_gap > ENDPOINT_MAX_OFFSET_M:
                    problems.append(f"{rid}: endpoint stop {sid} is {end_gap:.0f} m from the path end")
            print(
                f"   {sid} {stops_spec[sid]['name']:<36} {proj.distance_along_m / 1000:6.2f} km  "
                f"offset {proj.offset_m:6.1f} m  {tag}"
            )

        route_features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[round(x, 6), round(y, 6)] for x, y in coords],
                },
                "properties": {
                    "id": rid,
                    "name": rs["name"],
                    "color": rs["color"],
                    "campus_id": spec["campus_id"],
                    "segment_classes": rle(classes),
                    "stops": [{"stop_id": sid} for sid in rs["stops"]],
                    "authoring": {"waypoints": rs["waypoints"], "spurs_removed": spurs},
                },
            }
        )

    # Dwell depends on how many routes share a stop, known only after all routes are processed.
    for feat in route_features:
        for st in feat["properties"]["stops"]:
            sid = st["stop_id"]
            if stops_spec[sid].get("terminal"):
                st["dwell_s"] = spec["terminal_dwell_s"]
            elif len(usage[sid]) > 1:
                st["dwell_s"] = spec["shared_stop_dwell_s"]
            else:
                st["dwell_s"] = spec["default_dwell_s"]

    unused = [sid for sid, used in usage.items() if not used]
    if unused:
        problems.append(f"stops not used by any route: {unused}")

    shared = {sid: r for sid, r in usage.items() if len(r) > 1 and not stops_spec[sid].get("terminal")}
    print("\nShared stops:")
    for sid, r in shared.items():
        print(f"   {sid} {stops_spec[sid]['name']:<36} {', '.join(r)}")

    attribution = (
        "Road geometry © OpenStreetMap contributors (ODbL), routed with OSRM. "
        "Campus, stops and routes are fictional."
    )
    stops_fc = {
        "type": "FeatureCollection",
        "attribution": attribution,
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(canonical[sid][0], 6), round(canonical[sid][1], 6)],
                },
                "properties": {
                    "id": sid,
                    "name": s["name"],
                    "campus_id": spec["campus_id"],
                    "is_campus_terminal": bool(s.get("terminal")),
                    "walk_radius_m": 600 if s.get("terminal") else 400,
                },
            }
            for sid, s in sorted(stops_spec.items())
            if sid in canonical
        ],
    }
    routes_fc = {"type": "FeatureCollection", "attribution": attribution, "features": route_features}
    return stops_fc, routes_fc, problems


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="report only; do not write seed files")
    args = parser.parse_args()

    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    stops_fc, routes_fc, problems = author(spec)

    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f"   - {p}")
        return 1
    if args.check:
        print("\n--check: nothing written")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, fc in (("stops.geojson", stops_fc), ("routes.geojson", routes_fc)):
        path = OUT_DIR / name
        path.write_text(json.dumps(fc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
