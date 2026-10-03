/**
 * The bus network as served by the backend, plus indexes derived from it.
 *
 * Nothing here is hardcoded: stops come from `GET /stops`, routes from
 * `GET /routes` + `GET /routes/{id}`. "Shared stop" is derived from the
 * route details (a non-terminal stop served by more than one physical route).
 */
import { useCallback } from "react";

import { useApi } from "../api/ApiContext";
import type { RouteDetailOut, RouteSummaryOut, StopOut } from "../api/types";
import { useAsync } from "../hooks/useAsync";

export interface Network {
  stops: StopOut[];
  stopById: Map<string, StopOut>;
  routes: RouteDetailOut[];
  routeById: Map<string, RouteDetailOut>;
  summaries: RouteSummaryOut[];
  /** stop id → physical route ids serving it (either direction), sorted. */
  servingRoutes: Map<string, string[]>;
  sharedStopIds: Set<string>;
}

export function buildNetwork(
  stops: StopOut[],
  summaries: RouteSummaryOut[],
  routes: RouteDetailOut[],
): Network {
  const servingSets = new Map<string, Set<string>>();
  for (const r of routes) {
    for (const d of r.directions) {
      for (const s of d.stops) {
        let set = servingSets.get(s.stop_id);
        if (!set) servingSets.set(s.stop_id, (set = new Set()));
        set.add(r.id);
      }
    }
  }
  const servingRoutes = new Map<string, string[]>(
    [...servingSets].map(([id, set]) => [id, [...set].sort()]),
  );
  const stopById = new Map(stops.map((s) => [s.id, s]));
  const sharedStopIds = new Set(
    [...servingRoutes]
      .filter(([id, ids]) => ids.length > 1 && !stopById.get(id)?.is_campus_terminal)
      .map(([id]) => id),
  );
  const sortedRoutes = [...routes].sort((a, b) =>
    a.id.localeCompare(b.id, "en", { numeric: true }),
  );
  return {
    stops,
    stopById,
    routes: sortedRoutes,
    routeById: new Map(sortedRoutes.map((r) => [r.id, r])),
    summaries,
    servingRoutes,
    sharedStopIds,
  };
}

/** Load the whole static network from the backend (stops, routes, route geometry). */
export function useNetwork() {
  const api = useApi();
  const load = useCallback(async () => {
    const [stops, summaries] = await Promise.all([api.listStops(), api.listRoutes()]);
    const routes = await Promise.all(summaries.map((r) => api.getRoute(r.id)));
    return buildNetwork(stops, summaries, routes);
  }, [api]);
  return useAsync(load, "network");
}
