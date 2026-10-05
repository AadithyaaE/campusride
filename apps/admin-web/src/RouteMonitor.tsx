/**
 * Route monitor for the selected bus (Feature 10) + demo deviation controls.
 *
 * Status, distance, planned route and position all come from
 * `GET /buses/{id}/route-status`; the controls call `POST /sim/route-deviation`,
 * which changes the SYNTHETIC bus position in the backend simulator. The route
 * remains the planned route. Nothing is classified or measured in the browser.
 */
import { lazy, Suspense, useCallback, useEffect, useState } from "react";

import type { AdminApi, RouteDeviationDemoMode, RouteStatusResponse } from "./api/client";
import { timeFmt } from "./format";
import { ROUTE_LABEL, routeTone } from "./labels";
import { POLL_MS } from "./polling";

const RouteMap = lazy(() => import("./RouteMap"));

const CONTROLS: { mode: RouteDeviationDemoMode; label: string }[] = [
  { mode: "normal", label: "Normal" },
  { mode: "minor", label: "Simulate Minor Deviation" },
  { mode: "major", label: "Simulate Major Deviation" },
];

export function RouteMonitor({ api, busId }: { api: AdminApi; busId: string }) {
  const [rs, setRs] = useState<RouteStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<RouteDeviationDemoMode | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () =>
      api.routeStatus(busId).then(
        (r) => (setRs(r), setError(null)),
        (e: unknown) => setError(e instanceof Error ? e.message : String(e)),
      ),
    [api, busId],
  );
  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const control = (m: RouteDeviationDemoMode) => {
    setBusy(true);
    api
      .setRouteDeviation(m, busId)
      .then((st) => {
        setMode(
          (st.route_deviation[busId] ??
            st.route_deviation["*"] ??
            "normal") as RouteDeviationDemoMode,
        );
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        setBusy(false);
        void load();
      });
  };

  const tone = routeTone(rs?.route_status);
  return (
    <section className="subpanel" aria-label="Route monitor">
      <header className="panel-head">
        <h3>Route monitor · BUS {busId}</h3>
        <span className="sim-tag">Demo GPS</span>
      </header>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {rs && (
        <>
          <p className={`route-status route-${tone}`} role="status" aria-label="Route status">
            <strong>Route status: {ROUTE_LABEL[rs.route_status] ?? rs.route_status}</strong>
            {rs.deviation_distance_m !== null && (
              <span> · {Math.round(rs.deviation_distance_m)} m from planned route</span>
            )}
          </p>
          {rs.message && rs.route_status === "MAJOR_DEVIATION" && (
            <p className="route-banner" role="alert">
              {rs.message}
            </p>
          )}
          <p className="muted small">
            Trip {rs.trip_id ?? "—"} · {rs.route_direction_id ?? "—"} · fix{" "}
            {rs.timestamp ? timeFmt.format(new Date(rs.timestamp)) : "—"} · thresholds:{" "}
            {rs.thresholds.minor_m} m / {rs.thresholds.major_m} m
          </p>
          {rs.expected_route && (
            <Suspense fallback={<div className="route-map">Loading map…</div>}>
              <RouteMap
                route={rs.expected_route.coordinates}
                bus={rs.current_location}
                nearest={rs.nearest_route_point}
                status={rs.route_status}
                busLabel={`BUS ${busId}`}
              />
            </Suspense>
          )}
        </>
      )}
      <div className="controls" role="group" aria-label="Route deviation demo">
        {CONTROLS.map((c) => (
          <button
            key={c.mode}
            type="button"
            className={`btn${mode === c.mode ? " btn-primary" : ""}`}
            disabled={busy}
            onClick={() => control(c.mode)}
          >
            {c.label}
          </button>
        ))}
      </div>
      <p className="footnote">
        Demo controls shift this bus’s simulated GPS away from its route; the planned route itself
        never changes.
      </p>
    </section>
  );
}
