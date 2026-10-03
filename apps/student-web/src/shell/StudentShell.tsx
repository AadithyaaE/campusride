import { useCallback, useMemo, useState } from "react";

import type { MeOut } from "../api/types";
import { EmptyState, ErrorState, Loading } from "../components/StateViews";
import { useMyAssignment } from "../data/assignment";
import { useNetwork, type Network } from "../data/network";
import { useLiveFleet } from "../data/liveFleet";
import type { BusView } from "../features/dashboard/BusList";
import { DashboardPanel, type DashboardData } from "../features/dashboard/DashboardPanel";
import { dashboardAlerts, otherArrivals } from "../features/dashboard/interim";
import { MyBusPanel } from "../features/mybus/MyBusPanel";
import { RoutesPanel } from "../features/routes/RoutesPanel";
import { StopsPanel } from "../features/stops/StopsPanel";
import { useHealth } from "../hooks/useHealth";
import { localHour, suggestedDirection } from "../lib/format";
import MapView, { type MapBus, type MapRoute, type MapStop } from "../map/MapView";
import { Header } from "./Header";
import { TABS, useViewState } from "./urlState";

interface Props {
  me: MeOut;
  onLogout: () => void;
}

/** Scroll a dashboard section into view after the tab has rendered. */
function scrollToSection(id: string) {
  requestAnimationFrame(() =>
    document.getElementById(id)?.scrollIntoView?.({ behavior: "smooth" }),
  );
}

export function StudentShell({ me, onLogout }: Props) {
  const network = useNetwork();
  const health = useHealth();
  const [view, setView] = useViewState();
  const assignment = useMyAssignment();
  const fleet = useLiveFleet(); // polls backend bus state (no browser-side simulation)
  const [center, setCenter] = useState<{ lat: number; lng: number } | null>(null);
  const [tilesDown, setTilesDown] = useState(false);
  const [busView, setBusView] = useState<BusView>("stop");
  const [focusedBusId, setFocusedBusId] = useState<string | null>(null); // map highlight only

  const defaultDirection = suggestedDirection(
    health.health ? localHour(health.health.clock.local_now) : null,
  );
  // College-assigned transport (read-only, from the backend).
  const myAssignment = assignment.status === "success" ? assignment.data.assignment : null;
  const myStopId = myAssignment?.boarding_stop.stop_id ?? null;

  // Interim estimates layered on the BACKEND's matching / ETA / comparison (assigned only).
  const data = useMemo<DashboardData>(() => {
    const arrivals = fleet.arrivals;
    if (!arrivals || arrivals.status !== "assigned") {
      return { atMyStop: [], alerts: [] };
    }
    return {
      atMyStop: otherArrivals(arrivals), // backend ETA order
      alerts: dashboardAlerts(arrivals, fleet.commute, fleet.options, fleet.buses ?? []),
    };
  }, [fleet.arrivals, fleet.commute, fleet.options, fleet.buses]);

  const paused = fleet.sim?.paused ?? false;
  // Map markers: backend coordinates; highlight my bus and buses the BACKEND says serve my stop.
  const mapBuses = useMemo<MapBus[]>(() => {
    const serving = new Set(otherArrivals(fleet.arrivals).map((b) => b.bus_id));
    const mine = myAssignment?.bus.id;
    return (fleet.buses ?? [])
      .filter((b) => b.live)
      .map((b) => ({
        id: b.id,
        lnglat: b.live!.location.coordinates,
        color:
          (network.status === "success" && network.data.routeById.get(b.route_id)?.color) ||
          "#475569",
        label: b.id,
        highlight: b.id === mine,
        serving: b.id !== mine && serving.has(b.id),
        focused: b.id === focusedBusId,
        title: `Bus ${b.id} · ${b.live!.route_direction_id ?? b.route_id} · ${b.live!.status} (simulated)${
          serving.has(b.id) ? " · serves your stop" : ""
        }`,
      }));
  }, [fleet.buses, fleet.arrivals, myAssignment, network.status, network.data, focusedBusId]);

  const selectStop = useCallback(
    (stopId: string | null) =>
      setView({ stop: stopId, ...(stopId ? { tab: "stops" as const } : {}) }),
    [setView],
  );
  const selectRoute = useCallback(
    (routeId: string | null) =>
      setView({ route: routeId, ...(routeId ? { tab: "routes" as const } : {}) }),
    [setView],
  );
  const openSection = (id: string) => {
    setView({ tab: "dashboard" });
    scrollToSection(id);
  };

  return (
    <div className="app">
      <Header
        me={me}
        health={health}
        boardingStopName={myAssignment?.boarding_stop.name ?? null}
        alertCount={data.alerts.length}
        onOpenAlerts={() => openSection("alerts")}
        onLogout={onLogout}
      />
      <main className="main">
        <div className="map-wrap">
          {network.status === "success" ? (
            <NetworkMap
              network={network.data}
              buses={mapBuses}
              selectedRouteId={view.route}
              selectedStopId={view.stop}
              myStopId={myStopId}
              onSelectStop={selectStop}
              onSelectRoute={selectRoute}
              onViewChange={setCenter}
              onTilesUnavailable={() => setTilesDown(true)}
            />
          ) : (
            <div className="map map-placeholder">
              {network.status === "loading" ? <Loading label="Loading the bus network…" /> : null}
            </div>
          )}
          {tilesDown && (
            <div className="map-banner" role="status">
              Map tiles unavailable — routes and stops are still shown.
            </div>
          )}
          {mapBuses.length > 0 && (
            <div className="map-sim-badge" role="note">
              Simulated live tracking{paused ? " · paused" : ""}
            </div>
          )}
          <ul className="map-legend" aria-label="Map legend">
            <li>
              <span className="legend-dot" /> Stop
            </li>
            <li>
              <span className="legend-dot is-shared" /> Shared
            </li>
            <li>
              <span className="legend-dot is-mine" /> My boarding stop
            </li>
            {myAssignment && mapBuses.length > 0 && (
              <>
                <li>
                  <span className="legend-bus" /> My bus
                </li>
                <li>
                  <span className="legend-bus is-serving" /> Serves my stop
                </li>
              </>
            )}
          </ul>
        </div>

        <aside className="panel">
          <nav className="tabs" aria-label="Sections">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`tab${view.tab === t.id ? " is-active" : ""}`}
                aria-current={view.tab === t.id ? "page" : undefined}
                onClick={() => setView({ tab: t.id })}
              >
                {t.label}
              </button>
            ))}
          </nav>
          <div className="panel-scroll">
            {network.status === "loading" && (
              <Loading label="Loading stops and routes from the backend…" />
            )}
            {network.status === "error" && (
              <ErrorState error={network.error} onRetry={network.reload} />
            )}
            {network.status === "success" &&
              (network.data.stops.length === 0 || network.data.routes.length === 0 ? (
                <EmptyState title="No network data">
                  The backend returned no stops or routes. Seed the database with{" "}
                  <code>python scripts/seed_db.py</code>.
                </EmptyState>
              ) : (
                <>
                  {view.tab === "dashboard" && (
                    <DashboardPanel
                      firstName={me.name.split(" ")[0] ?? me.name}
                      network={network.data}
                      assignment={assignment}
                      fleet={fleet}
                      data={data}
                      busView={busView}
                      onBusViewChange={setBusView}
                      selectedBusId={focusedBusId}
                      onSelectBus={setFocusedBusId}
                      onViewStop={(stopId) => selectStop(stopId)}
                      onViewRoute={(routeId) => selectRoute(routeId)}
                      onViewAllBuses={() => {
                        setBusView("all");
                        scrollToSection("buses");
                      }}
                    />
                  )}
                  {view.tab === "mybus" && (
                    <MyBusPanel
                      network={network.data}
                      assignment={assignment}
                      onShowOnMap={(route, stop) => setView({ route, stop })}
                    />
                  )}
                  {view.tab === "stops" && (
                    <StopsPanel
                      network={network.data}
                      selectedStopId={view.stop}
                      myStopId={myStopId}
                      mapCenter={center}
                      onSelectStop={selectStop}
                      onSelectRoute={selectRoute}
                    />
                  )}
                  {view.tab === "routes" && (
                    <RoutesPanel
                      network={network.data}
                      selectedRouteId={view.route}
                      myStopId={myStopId}
                      defaultDirection={defaultDirection}
                      onSelectRoute={selectRoute}
                      onSelectStop={selectStop}
                    />
                  )}
                </>
              ))}
          </div>
        </aside>
      </main>
    </div>
  );
}

function NetworkMap({
  network,
  buses,
  ...rest
}: {
  network: Network;
  buses: MapBus[];
  selectedRouteId: string | null;
  selectedStopId: string | null;
  myStopId: string | null;
  onSelectStop: (id: string) => void;
  onSelectRoute: (id: string) => void;
  onViewChange: (c: { lat: number; lng: number }) => void;
  onTilesUnavailable: () => void;
}) {
  const routes = useMemo<MapRoute[]>(
    () =>
      network.routes.map((r) => ({
        id: r.id,
        color: r.color,
        name: r.name,
        path: r.path.coordinates,
      })),
    [network],
  );
  const stops = useMemo<MapStop[]>(
    () =>
      network.stops.map((s) => ({
        id: s.id,
        name: s.name,
        lnglat: s.location.coordinates,
        shared: network.sharedStopIds.has(s.id),
        terminal: s.is_campus_terminal,
      })),
    [network],
  );
  return <MapView routes={routes} stops={stops} buses={buses} {...rest} />;
}
