/**
 * Leaflet map for one bus vs. its PLANNED route (Feature 10). Draws exactly what the
 * backend returned: the planned route line, the tracked bus position and (when the
 * backend found one) the nearest point of the route. No distances are computed here.
 */
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";

import type { RouteStatus } from "./api/client";

const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

export interface LatLon {
  lat: number;
  lon: number;
}

export interface RouteMapProps {
  /** Planned route, GeoJSON order [lng, lat] (from the backend). */
  route: [number, number][];
  bus: LatLon | null;
  nearest: LatLon | null;
  status: RouteStatus;
  busLabel: string;
}

const COLOR: Partial<Record<RouteStatus, string>> = {
  NORMAL: "#16a34a",
  MINOR_DEVIATION: "#d97706",
  MAJOR_DEVIATION: "#dc2626",
};

export default function RouteMap({ route, bus, nearest, status, busLabel }: RouteMapProps) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const fittedFor = useRef<string | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const m = L.map(el.current, { zoomControl: true }).setView([12.9, 80.2], 12);
    L.tileLayer(TILE_URL, { attribution: ATTRIBUTION, maxZoom: 19 }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    fittedFor.current = null; // a (re)created map (e.g. StrictMode remount) must be fitted again
    const ro = new ResizeObserver(() => {
      m.invalidateSize();
      fittedFor.current = null; // refit on the next data update once the size is known
    });
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      m.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    const g = layer.current;
    if (!m || !g) return;
    g.clearLayers();
    const line = L.polyline(
      route.map(([lng, lat]) => [lat, lng] as [number, number]),
      { color: "#2563eb", weight: 6, opacity: 0.8 },
    )
      .bindTooltip("Planned route")
      .addTo(g);
    if (bus) {
      if (nearest) {
        L.polyline(
          [
            [bus.lat, bus.lon],
            [nearest.lat, nearest.lon],
          ],
          { color: COLOR[status] ?? "#64748b", weight: 3, dashArray: "6 6" },
        ).addTo(g);
      }
      L.circleMarker([bus.lat, bus.lon], {
        radius: 10,
        color: "#0f172a",
        weight: 3,
        fillColor: COLOR[status] ?? "#64748b",
        fillOpacity: 1,
      })
        .bindTooltip(`${busLabel} · tracked position`, { permanent: true, direction: "top" })
        .addTo(g);
    }
    // Fit once per bus (and when the bus first leaves the route) — not on every poll.
    const key = `${busLabel}:${nearest ? "off" : "on"}`;
    if (fittedFor.current !== key) {
      fittedFor.current = key;
      m.invalidateSize(); // the container may have just been laid out (lazy-loaded panel)
      if (bus && nearest) {
        m.fitBounds(
          L.latLngBounds([
            [bus.lat, bus.lon],
            [nearest.lat, nearest.lon],
          ]).pad(0.6),
          { maxZoom: 17 },
        );
      } else if (bus) {
        m.setView([bus.lat, bus.lon], 15);
      } else {
        m.fitBounds(line.getBounds(), { padding: [24, 24] });
      }
    }
  }, [route, bus, nearest, status, busLabel]);

  return <div ref={el} className="route-map" role="region" aria-label="Route deviation map" />;
}
