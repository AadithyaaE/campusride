/**
 * MapView adapter — Leaflet + OpenStreetMap today, swappable for Google Maps later.
 *
 * The rest of the app passes plain data (backend coordinates in [lng, lat])
 * and callbacks; nothing outside this folder imports Leaflet.
 *
 * `buses` takes bus positions. Today they come from the synthetic demo
 * simulator (src/demo); in Phase 2 they come from real telemetry over the WebSocket.
 */
import L from "leaflet";
import { useEffect, useRef } from "react";

import type { LngLat } from "../api/types";
import { config } from "../config";
import { boundsOf, toLatLng } from "./geo";

export interface MapRoute {
  id: string;
  color: string;
  name: string;
  path: LngLat[];
}

export interface MapStop {
  id: string;
  name: string;
  lnglat: LngLat;
  shared: boolean;
  terminal: boolean;
}

export interface MapBus {
  id: string;
  lnglat: LngLat;
  color: string;
  label: string;
  /** The student's own (assigned) bus — drawn larger and on top. */
  highlight?: boolean;
  /** Serves the student's boarding stop (per backend matching) — outlined. */
  serving?: boolean;
  /** Picked from a bus-options card — ringed and centred once. */
  focused?: boolean;
  title?: string;
}

export interface MapViewProps {
  routes: MapRoute[];
  stops: MapStop[];
  buses: MapBus[];
  selectedRouteId: string | null;
  selectedStopId: string | null;
  myStopId: string | null;
  onSelectStop: (stopId: string) => void;
  onSelectRoute: (routeId: string) => void;
  onViewChange?: (center: { lat: number; lng: number }) => void;
  onTilesUnavailable?: () => void;
}

const PAD: L.FitBoundsOptions = { padding: [32, 32] };

export default function MapView(props: MapViewProps) {
  const { routes, stops, buses, selectedRouteId, selectedStopId, myStopId } = props;
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const routeLayer = useRef<L.LayerGroup | null>(null);
  const stopLayer = useRef<L.LayerGroup | null>(null);
  const busLayer = useRef<L.LayerGroup | null>(null);
  const lines = useRef(new Map<string, L.Polyline>());
  const fitted = useRef(false);
  const cb = useRef(props);
  useEffect(() => {
    cb.current = props; // latest callbacks for Leaflet event handlers
  });

  // Create the map once.
  useEffect(() => {
    if (!el.current) return;
    const m = L.map(el.current, { zoomControl: true, preferCanvas: false }).setView([0, 0], 2);
    let tileErrors = 0;
    L.tileLayer(config.tileUrl, { attribution: config.tileAttribution, maxZoom: 19 })
      .on("tileerror", () => {
        tileErrors += 1;
        if (tileErrors === 3) cb.current.onTilesUnavailable?.();
      })
      .addTo(m);
    routeLayer.current = L.layerGroup().addTo(m);
    stopLayer.current = L.layerGroup().addTo(m);
    busLayer.current = L.layerGroup().addTo(m);
    m.on("moveend", () => {
      const c = m.getCenter();
      cb.current.onViewChange?.({ lat: c.lat, lng: c.lng });
    });
    map.current = m;
    fitted.current = false; // a (re)created map has not been fitted yet (StrictMode remounts)

    const ro = new ResizeObserver(() => m.invalidateSize());
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      m.remove();
      map.current = null;
    };
  }, []);

  // Route polylines (+ fit everything on first data).
  useEffect(() => {
    const layer = routeLayer.current;
    const m = map.current;
    if (!layer || !m) return;
    layer.clearLayers();
    lines.current.clear();
    for (const r of routes) {
      const line = L.polyline(r.path.map(toLatLng), {
        color: r.color,
        weight: 5,
        opacity: 0.85,
        lineCap: "round",
        lineJoin: "round",
      })
        .bindTooltip(`${r.id} · ${r.name}`, { sticky: true })
        .on("click", () => cb.current.onSelectRoute(r.id));
      line.addTo(layer);
      lines.current.set(r.id, line);
    }
    if (!fitted.current && routes.length > 0) {
      const b = boundsOf(routes.flatMap((r) => r.path));
      if (b) m.fitBounds(b, PAD);
      fitted.current = true;
    }
  }, [routes]);

  // Highlight the selected route, dim the others.
  useEffect(() => {
    for (const [id, line] of lines.current) {
      const selected = id === selectedRouteId;
      line.setStyle({
        weight: selected ? 7 : 5,
        opacity: selectedRouteId === null ? 0.85 : selected ? 1 : 0.25,
      });
      if (selected) line.bringToFront();
    }
    const route = routes.find((r) => r.id === selectedRouteId);
    const b = route ? boundsOf(route.path) : null;
    if (b && map.current) map.current.fitBounds(b, PAD);
  }, [selectedRouteId, routes]);

  // Stops (redrawn on selection change — the network is small).
  useEffect(() => {
    const layer = stopLayer.current;
    if (!layer) return;
    layer.clearLayers();
    for (const s of stops) {
      const selected = s.id === selectedStopId;
      const mine = s.id === myStopId;
      const pos = toLatLng(s.lnglat);
      const marker = s.terminal
        ? L.marker(pos, {
            icon: L.divIcon({
              className: "map-campus-pin",
              html: `<span>Campus</span>`,
              iconSize: undefined,
            }),
            keyboard: true,
            title: s.name,
          })
        : L.circleMarker(pos, {
            radius: selected || mine ? 9 : s.shared ? 7 : 5,
            color: mine ? "#0f3d5e" : selected ? "#111827" : "#334155",
            weight: s.shared || selected || mine ? 3 : 2,
            fillColor: mine ? "#38bdf8" : s.shared ? "#fde68a" : "#ffffff",
            fillOpacity: 1,
          });
      marker
        .bindTooltip(
          `${s.name}${s.shared ? " · shared stop" : ""}${mine ? " · my boarding stop" : ""}`,
          {
            direction: "top",
            offset: [0, -6],
          },
        )
        .on("click", () => cb.current.onSelectStop(s.id))
        .addTo(layer);
    }
  }, [stops, selectedStopId, myStopId]);

  // Centre on a newly selected stop.
  useEffect(() => {
    const s = stops.find((x) => x.id === selectedStopId);
    if (s && map.current) {
      map.current.setView(toLatLng(s.lnglat), Math.max(map.current.getZoom(), 15), {
        animate: true,
      });
    }
  }, [selectedStopId, stops]);

  // Bus markers (synthetic demo now; real telemetry in Phase 2).
  useEffect(() => {
    const layer = busLayer.current;
    if (!layer) return;
    layer.clearLayers();
    for (const b of buses) {
      L.marker(toLatLng(b.lnglat), {
        icon: L.divIcon({
          className: `map-bus-pin${b.highlight ? " is-mine" : b.serving ? " is-serving" : ""}${
            b.focused ? " is-focused" : ""
          }`,
          html: `<span style="background:${b.color}">${b.label}</span>`,
        }),
        title: b.title ?? b.id,
        zIndexOffset: b.focused ? 1100 : b.highlight ? 1000 : b.serving ? 700 : 500,
        keyboard: false,
      }).addTo(layer);
    }
  }, [buses]);

  // Pan to a bus when it becomes focused (once per selection, not on every poll).
  const focused = buses.find((b) => b.focused);
  const focusedId = focused?.id ?? null;
  const focusedAt = useRef<string | null>(null);
  useEffect(() => {
    if (focusedId === focusedAt.current) return;
    focusedAt.current = focusedId;
    if (focused && map.current) {
      map.current.panTo(toLatLng(focused.lnglat), { animate: true });
    }
  }, [focusedId, focused]);

  return <div ref={el} className="map" role="region" aria-label="Bus network map" />;
}
