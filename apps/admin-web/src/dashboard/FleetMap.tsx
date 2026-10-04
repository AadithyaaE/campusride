/**
 * Live fleet map (Feature 13) — Leaflet + OpenStreetMap, like the existing route map.
 * Draws exactly what the backend returned: each route's planned geometry
 * (`GET /routes/{id}`) and each bus's TRACKED position, status and label
 * (`GET /admin/fleet`). Nothing is positioned, matched or classified here.
 */
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";

import type { FleetBus } from "../api/client";
import { busNo } from "../format";
import { OPS_LABEL } from "../labels";

const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

export interface MapRoute {
  id: string;
  name: string;
  color: string;
  /** Planned geometry, GeoJSON order [lng, lat]. */
  coords: [number, number][];
}

export interface FleetMapProps {
  routes: MapRoute[];
  buses: FleetBus[];
  selectedBusId: string | null;
  focusRouteId: string | null;
  onSelectBus: (busId: string) => void;
}

const escapeHtml = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

export default function FleetMap({
  routes,
  buses,
  selectedBusId,
  focusRouteId,
  onSelectBus,
}: FleetMapProps) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const routeLayer = useRef<L.LayerGroup | null>(null);
  const busLayer = useRef<L.LayerGroup | null>(null);
  const fitted = useRef(false);
  const onSelect = useRef(onSelectBus);
  useEffect(() => {
    onSelect.current = onSelectBus;
  }, [onSelectBus]);

  useEffect(() => {
    if (!el.current) return;
    const m = L.map(el.current, { zoomControl: true, attributionControl: true }).setView(
      [12.95, 80.2],
      11,
    );
    L.tileLayer(TILE_URL, { attribution: ATTRIBUTION, maxZoom: 19 }).addTo(m);
    routeLayer.current = L.layerGroup().addTo(m);
    busLayer.current = L.layerGroup().addTo(m);
    map.current = m;
    fitted.current = false;
    const ro = new ResizeObserver(() => m.invalidateSize());
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      m.remove();
      map.current = null;
    };
  }, []);

  // Planned routes (static) — the focused route is drawn on top and bolder.
  useEffect(() => {
    const m = map.current;
    const g = routeLayer.current;
    if (!m || !g) return;
    g.clearLayers();
    const bounds = L.latLngBounds([]);
    const ordered = [...routes].sort(
      (a, b) => Number(a.id === focusRouteId) - Number(b.id === focusRouteId),
    );
    for (const r of ordered) {
      const latlngs = r.coords.map(([lng, lat]) => [lat, lng] as [number, number]);
      const focused = r.id === focusRouteId;
      L.polyline(latlngs, {
        color: r.color,
        weight: focused ? 7 : 4,
        opacity: focusRouteId && !focused ? 0.35 : 0.85,
      })
        .bindTooltip(`${r.id} · ${r.name}`, { sticky: true })
        .addTo(g);
      latlngs.forEach((p) => bounds.extend(p));
    }
    if (!fitted.current && bounds.isValid()) {
      fitted.current = true;
      m.invalidateSize();
      m.fitBounds(bounds, { padding: [20, 20] });
    }
  }, [routes, focusRouteId]);

  // Buses — redrawn on every poll from the backend's positions.
  useEffect(() => {
    const g = busLayer.current;
    if (!g) return;
    g.clearLayers();
    for (const b of buses) {
      if (!b.location) continue;
      const selected = b.bus_id === selectedBusId;
      const dev =
        b.route_status === "MAJOR_DEVIATION"
          ? " dev-major"
          : b.route_status === "MINOR_DEVIATION"
            ? " dev-minor"
            : "";
      const icon = L.divIcon({
        className: "bus-pin-wrap",
        html: `<span class="bus-pin st-${b.operational_status}${dev}${selected ? " is-selected" : ""}" style="--route:${escapeHtml(b.route_color)}">${escapeHtml(busNo(b.bus_id))}</span>`,
        iconSize: [34, 22],
        iconAnchor: [17, 11],
      });
      const tip = [
        `Bus ${b.bus_id}`,
        `${b.route_id}${b.direction_label ? ` · ${b.direction_label}` : ""}`,
        OPS_LABEL[b.operational_status] ?? b.operational_status,
        b.speed_kmh !== null ? `${b.speed_kmh} km/h` : null,
      ]
        .filter(Boolean)
        .join(" · ");
      L.marker([b.location.lat, b.location.lon], {
        icon,
        zIndexOffset: selected ? 1000 : b.operational_status === "deviated" ? 500 : 0,
        keyboard: true,
        title: `Bus ${b.bus_id}`,
      })
        .bindTooltip(escapeHtml(tip), { direction: "top", offset: [0, -10] })
        .on("click", () => onSelect.current(b.bus_id))
        .addTo(g);
    }
  }, [buses, selectedBusId]);

  // Follow the selected bus when it changes (not on every poll).
  useEffect(() => {
    const m = map.current;
    const b = buses.find((x) => x.bus_id === selectedBusId);
    if (m && b?.location) m.panTo([b.location.lat, b.location.lon], { animate: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pan only when the selection changes
  }, [selectedBusId]);

  return <div ref={el} className="fleet-map" role="region" aria-label="Live fleet map" />;
}
