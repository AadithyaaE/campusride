/**
 * Transport control room (Feature 13) — the admin dashboard's single operational view.
 *
 * Data flow (Feature 14): REST loads every resource once, then ONE WebSocket pushes changes:
 *   fleet.bus.updated       → the bus's /admin/fleet row (map, table, panels, bus detail)
 *   admin.overview.updated  → KPI cards
 *   alert.*                 → alert summary + list
 *   trip.* / sim.reset      → re-fetch routes + schedule (+ everything on reset)
 * After every (re)connection the REST state is fetched once. While the socket is down the
 * live resources fall back to REST polling every 10 s; while it is live REST only re-syncs
 * every 60 s. Routes/schedule refresh every 15 s, analytics every 20 s, route geometry once.
 * The backend stays authoritative for every number; this view only selects and shows.
 */
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { AdminApi, AdminOverview, AlertOut, FleetBus, RouteDetail } from "../api/client";
import { dateFmt, timeFmt } from "../format";
import { ANALYTICS_POLL_MS, FALLBACK_POLL_MS, RESYNC_MS, SLOW_POLL_MS } from "../polling";
import type { RealtimeStatus, WsEnvelope } from "../realtime/client";
import { useRealtime } from "../realtime/useRealtime";
import { usePoll } from "../usePoll";
import { AlertsList, AlertSummary } from "./Alerts";
import { AnalyticsPanel } from "./Analytics";
import { BusDetail } from "./BusDetail";
import type { MapRoute } from "./FleetMap";
import { applyFleetFilter, type FleetFilter, isFiltered, NO_FILTER } from "./fleetFilter";
import { FleetFilters, FleetTable } from "./FleetTable";
import { DemoControls } from "./DemoControls";
import { FleetStatus } from "./FleetStatus";
import { KpiStrip } from "./Kpis";
import { ActiveBuses, DelaysPanel, DeviationsPanel, OccupancyPanel } from "./OpsPanels";
import { RouteDetailPanel, RoutesPanel, SchedulePanel } from "./RoutesSchedule";
import { useAlerts } from "./useAlerts";

const FleetMap = lazy(() => import("./FleetMap"));

type Selection = { kind: "bus"; id: string } | { kind: "route"; id: string } | null;

/** Route geometry + stops: static reference data, fetched once per route. */
function useRouteDetails(api: AdminApi, routeIds: string[]): Record<string, RouteDetail> {
  const [details, setDetails] = useState<Record<string, RouteDetail>>({});
  const key = routeIds.join(",");
  useEffect(() => {
    let cancelled = false;
    for (const id of key ? key.split(",") : []) {
      api.routeDetail(id).then(
        (d) => !cancelled && setDetails((prev) => (prev[id] ? prev : { ...prev, [id]: d })),
        () => undefined, // the map simply omits a route line it couldn't load
      );
    }
    return () => {
      cancelled = true;
    };
  }, [api, key]);
  return details;
}

/** Newer-or-equal backend fix wins (events may arrive late or twice). */
const isNewer = (next: FleetBus, cur: FleetBus) =>
  (next.last_updated ?? "") >= (cur.last_updated ?? "");

export function ControlRoom({ api }: { api: AdminApi }) {
  const [status, setStatus] = useState<RealtimeStatus>("connecting");
  const liveInterval = status === "live" ? RESYNC_MS : FALLBACK_POLL_MS;
  const fleet = usePoll(
    useCallback(() => api.adminFleet(), [api]),
    liveInterval,
  );
  const overview = usePoll(
    useCallback(() => api.adminOverview(), [api]),
    liveInterval,
  );
  const routes = usePoll(
    useCallback(() => api.adminRoutes(), [api]),
    SLOW_POLL_MS,
  );
  const schedule = usePoll(
    useCallback(() => api.adminSchedule(), [api]),
    SLOW_POLL_MS,
  );
  const analytics = usePoll(
    useCallback(() => api.adminAnalytics(), [api]),
    ANALYTICS_POLL_MS,
  );
  const alerts = useAlerts(api, liveInterval);
  const [lastEventTs, setLastEventTs] = useState<string | null>(null);

  const slowTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshTrips = () => {
    if (slowTimer.current) clearTimeout(slowTimer.current);
    slowTimer.current = setTimeout(() => {
      void routes.refresh();
      void schedule.refresh();
    }, 500);
  };
  const resync = () => {
    void fleet.refresh();
    void overview.refresh();
    void alerts.refresh();
    void routes.refresh();
    void schedule.refresh();
  };
  useRealtime(api, {
    onStatus: setStatus,
    onOpen: resync, // authoritative state once per (re)connection — no missed events
    onEvent: (e: WsEnvelope) => {
      if (e.type === "fleet.bus.updated") {
        const row = (e.data as { bus: FleetBus }).bus;
        fleet.mutate((prev) =>
          prev
            ? {
                ...prev,
                buses: prev.buses.map((b) =>
                  b.bus_id === row.bus_id && isNewer(row, b) ? row : b,
                ),
              }
            : prev,
        );
        setLastEventTs((t) => (t && t > e.ts ? t : e.ts));
      } else if (e.type === "admin.overview.updated") {
        overview.mutate(() => e.data as unknown as AdminOverview);
      } else if (e.type === "alert.created" || e.type === "alert.updated") {
        alerts.apply(
          e.type === "alert.created" ? "created" : "updated",
          e.data as unknown as AlertOut,
        );
      } else if (e.type === "alert.resolved") {
        alerts.apply("resolved", e.data as unknown as AlertOut);
      } else if (e.type === "alert.read") {
        alerts.apply("read", e.data as { alert_id: string });
      } else if (e.type === "trip.started" || e.type === "trip.completed") {
        refreshTrips();
      } else if (e.type === "sim.reset") {
        resync();
      }
    },
  });
  useEffect(
    () => () => {
      if (slowTimer.current) clearTimeout(slowTimer.current);
    },
    [],
  );

  const [filter, setFilter] = useState<FleetFilter>(NO_FILTER);
  const [selection, setSelection] = useState<Selection>(null);

  const all = useMemo(() => fleet.data?.buses ?? [], [fleet.data]);
  const filtered = useMemo(() => applyFleetFilter(all, filter), [all, filter]);
  const routeIds = useMemo(() => (routes.data ?? []).map((r) => r.id), [routes.data]);
  const details = useRouteDetails(api, routeIds);
  const mapRoutes: MapRoute[] = useMemo(
    () =>
      (routes.data ?? [])
        .filter((r) => details[r.id])
        .map((r) => ({
          id: r.id,
          name: r.name,
          color: r.color,
          coords: details[r.id]!.path.coordinates,
        })),
    [routes.data, details],
  );

  const selectBus = useCallback((id: string) => setSelection({ kind: "bus", id }), []);
  const selectRoute = useCallback((id: string) => setSelection({ kind: "route", id }), []);
  const close = useCallback(() => setSelection(null), []);
  const selectedBus =
    selection?.kind === "bus" ? all.find((b) => b.bus_id === selection.id) : undefined;
  const selectedRoute =
    selection?.kind === "route" ? routes.data?.find((r) => r.id === selection.id) : undefined;
  const simTime =
    [fleet.data?.sim_time, overview.data?.sim_time, lastEventTs]
      .filter((t): t is string => Boolean(t))
      .sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null;
  const offline = fleet.error !== null && status !== "live";

  return (
    <div className="control-room">
      <div className="statusbar" role="status" aria-label="Live status">
        <nav aria-label="Sections" className="section-nav">
          <a href="#map">Map</a>
          <a href="#fleet">Fleet</a>
          <a href="#ops">Operations</a>
          <a href="#routes">Routes</a>
          <a href="#schedule">Schedule</a>
          <a href="#analytics">Analytics</a>
        </nav>
        <span className="clock">
          {simTime ? (
            <>
              {dateFmt.format(new Date(simTime))} ·{" "}
              <strong className="mono">{timeFmt.format(new Date(simTime))}</strong> IST
            </>
          ) : (
            "—"
          )}
          <span className="sim-tag">Demo data</span>
        </span>
        <span
          className={`live ${offline ? "is-offline" : status === "live" ? "is-live" : "is-fallback"}`}
        >
          {offline
            ? "Connection lost"
            : status === "live"
              ? "Live · real-time"
              : fleet.data
                ? `Reconnecting… · polling every ${FALLBACK_POLL_MS / 1000}s`
                : "Connecting…"}
        </span>
      </div>

      {offline && (
        <p className="banner-error" role="alert">
          {fleet.error}
          {fleet.data ? " — showing the last data received." : ""}
        </p>
      )}

      <div className="top-row">
        <KpiStrip overview={overview.data} error={overview.error} />
        <AlertSummary alerts={alerts.alerts} onSelectBus={selectBus} />
      </div>

      <div className="ops-grid" id="map">
        <section className="panel map-panel" aria-label="Live fleet map panel">
          <header className="panel-head">
            <h2>Live fleet map</h2>
            <span className="legend small" aria-label="Map legend">
              <span className="pin-key st-active">Active</span>
              <span className="pin-key st-delayed">Delayed</span>
              <span className="pin-key st-deviated">Off route</span>
              <span className="pin-key st-waiting">Waiting</span>
              <span className="pin-key st-completed">Idle / done</span>
            </span>
          </header>
          {!fleet.data && !fleet.error ? (
            <div className="fleet-map placeholder">Loading live fleet…</div>
          ) : (
            <Suspense fallback={<div className="fleet-map placeholder">Loading map…</div>}>
              <FleetMap
                routes={mapRoutes}
                buses={filtered}
                selectedBusId={selectedBus?.bus_id ?? null}
                focusRouteId={selectedRoute?.id ?? (filter.route || null)}
                onSelectBus={selectBus}
              />
            </Suspense>
          )}
          <p className="footnote">
            Planned routes and live bus positions. Click a bus for details.
            {isFiltered(filter) && " Filters apply to the map."}
          </p>
        </section>
        <aside className="side" aria-label="Details">
          {selectedBus ? (
            <BusDetail
              api={api}
              bus={selectedBus}
              alerts={alerts.alerts}
              onClose={close}
              onSelectRoute={selectRoute}
            />
          ) : selectedRoute ? (
            <RouteDetailPanel
              key={selectedRoute.id}
              route={selectedRoute}
              detail={details[selectedRoute.id]}
              fleet={all}
              schedule={schedule.data}
              onSelectBus={selectBus}
              onClose={close}
            />
          ) : (
            <FleetStatus
              rows={all}
              onFilter={(status) => {
                setFilter({ ...NO_FILTER, status });
                document.getElementById("fleet")?.scrollIntoView?.({ behavior: "smooth" });
              }}
            />
          )}
          {!selectedBus && !selectedRoute && <DemoControls api={api} rows={all} />}
        </aside>
      </div>

      <section className="panel" aria-label="Live fleet" id="fleet">
        <header className="panel-head">
          <h2>
            Live fleet{" "}
            {fleet.data && (
              <span className="count">
                {filtered.length}
                {isFiltered(filter) ? ` of ${all.length}` : ""}
              </span>
            )}
          </h2>
          <FleetFilters fleet={fleet.data} filter={filter} onChange={setFilter} />
        </header>
        {!fleet.data ? (
          fleet.error ? (
            <p className="empty">Fleet data is unavailable.</p>
          ) : (
            <p className="muted">Loading live fleet…</p>
          )
        ) : (
          <FleetTable
            rows={filtered}
            total={all.length}
            selectedBusId={selectedBus?.bus_id ?? null}
            onSelectBus={selectBus}
            onSelectRoute={selectRoute}
          />
        )}
        <p className="footnote">ETA, occupancy, route status and delay update in real time.</p>
      </section>

      <ActiveBuses rows={filtered} onSelectBus={selectBus} />

      <div className="tri" id="ops">
        <OccupancyPanel rows={all} onSelectBus={selectBus} />
        <DeviationsPanel rows={all} onSelectBus={selectBus} />
        <DelaysPanel rows={all} onSelectBus={selectBus} />
      </div>

      <div className="duo">
        <RoutesPanel
          routes={routes.data}
          error={routes.error}
          selectedRouteId={selectedRoute?.id ?? null}
          onSelectRoute={selectRoute}
        />
        <AlertsList api={api} state={alerts} />
      </div>

      <SchedulePanel schedule={schedule.data} error={schedule.error} onSelectBus={selectBus} />

      <AnalyticsPanel analytics={analytics.data} error={analytics.error} />
    </div>
  );
}
