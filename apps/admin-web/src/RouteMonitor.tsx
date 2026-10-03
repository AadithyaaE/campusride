/**
 * Route monitor for the selected bus (Feature 10) + demo deviation controls.
 *
 * Status, distance, planned route and position all come from
 * `GET /buses/{id}/route-status`; the controls call `POST /sim/route-deviation`,
 * which changes the SYNTHETIC bus position in the backend simulator. The route
 * remains the planned route. Nothing is classified or measured in the browser.
 */
import { lazy, Suspense, useCallback, useEffect, useState } from "react";

import type { AdminApi, AlertOut, RouteDeviationDemoMode, RouteStatusResponse } from "./api/client";
import { ROUTE_LABEL } from "./labels";
import { POLL_MS } from "./polling";

const RouteMap = lazy(() => import("./RouteMap"));

const timeFmt = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

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

  const status = rs?.route_status ?? null;
  const tone =
    status === "MAJOR_DEVIATION"
      ? "major"
      : status === "MINOR_DEVIATION"
        ? "minor"
        : status === "NORMAL"
          ? "ok"
          : "na";
  return (
    <section className="card" aria-label="Route monitor">
      <header className="card-head">
        <h2>Route · BUS {busId}</h2>
        <span className="sim-tag">Synthetic GPS</span>
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
        Demo controls move this bus’s SYNTHETIC GPS sideways in the backend simulator; the planned
        route never changes. The backend re-evaluates on the next fix.
      </p>
    </section>
  );
}

export function AlertsPanel({ api }: { api: AdminApi }) {
  const [alerts, setAlerts] = useState<AlertOut[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api.alerts(true).then(
        (a) => !cancelled && setAlerts(a),
        () => undefined,
      );
    void load();
    const id = setInterval(() => void load(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [api]);
  return (
    <section className="card" aria-label="Active alerts">
      <header className="card-head">
        <h2>Active alerts</h2>
      </header>
      {alerts === null ? (
        <p className="muted">Loading…</p>
      ) : alerts.length === 0 ? (
        <p className="muted">No active alerts.</p>
      ) : (
        <ul className="alerts" aria-label="Alert list">
          {alerts.map((a) => (
            <li key={a.id} className={`alert alert-${a.severity}`}>
              <strong>{a.title}</strong>
              <span>{a.body}</span>
              <time dateTime={a.created_at} className="muted">
                {timeFmt.format(new Date(a.created_at))}
              </time>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
