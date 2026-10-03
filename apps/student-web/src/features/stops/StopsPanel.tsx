import { useMemo, useState } from "react";

import { useApi } from "../../api/ApiContext";
import type { NearbyStopOut } from "../../api/types";
import { RouteChip, SharedBadge } from "../../components/Badges";
import { EmptyState, ErrorState, Loading } from "../../components/StateViews";
import type { Network } from "../../data/network";
import { StopDetail } from "./StopDetail";

interface Props {
  network: Network;
  selectedStopId: string | null;
  myStopId: string | null;
  mapCenter: { lat: number; lng: number } | null;
  onSelectStop: (stopId: string | null) => void;
  onSelectRoute: (routeId: string) => void;
}

type Nearby =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; data: NearbyStopOut[] }
  | { status: "error"; error: Error };

const NEARBY_RADIUS_M = 2_000;

export function StopsPanel(props: Props) {
  const { network, selectedStopId, myStopId, mapCenter, onSelectStop } = props;
  const api = useApi();
  const [query, setQuery] = useState("");
  const [sharedOnly, setSharedOnly] = useState(false);
  const [nearby, setNearby] = useState<Nearby>({ status: "idle" });

  const stops = useMemo(() => {
    const q = query.trim().toLowerCase();
    return network.stops
      .filter((s) => !sharedOnly || network.sharedStopIds.has(s.id))
      .filter((s) => !q || s.name.toLowerCase().includes(q) || s.id.toLowerCase() === q)
      .sort((a, b) =>
        a.is_campus_terminal !== b.is_campus_terminal
          ? a.is_campus_terminal
            ? -1
            : 1
          : a.name.localeCompare(b.name),
      );
  }, [network, query, sharedOnly]);

  if (selectedStopId) {
    return (
      <div className="panel-body">
        <button type="button" className="link-back" onClick={() => onSelectStop(null)}>
          ← All stops
        </button>
        <StopDetail
          stopId={selectedStopId}
          network={network}
          myStopId={myStopId}
          onSelectRoute={props.onSelectRoute}
        />
      </div>
    );
  }

  const findNearby = () => {
    if (!mapCenter) return;
    setNearby({ status: "loading" });
    api
      .nearbyStops({ lat: mapCenter.lat, lng: mapCenter.lng, radiusM: NEARBY_RADIUS_M, limit: 5 })
      .then(
        (data) => setNearby({ status: "success", data }),
        (error: Error) => setNearby({ status: "error", error }),
      );
  };

  const color = (routeId: string) => network.routeById.get(routeId)?.color ?? "#64748b";

  return (
    <div className="panel-body">
      <h2 className="panel-title">Stops</h2>

      <div className="toolbar">
        <input
          type="search"
          className="input"
          placeholder="Search stops"
          aria-label="Search stops"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="check">
          <input
            type="checkbox"
            checked={sharedOnly}
            onChange={(e) => setSharedOnly(e.target.checked)}
          />
          Shared only
        </label>
      </div>

      <div className="nearby">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={findNearby}
          disabled={!mapCenter}
        >
          Stops near map centre
        </button>
        {nearby.status === "loading" && <Loading label="Finding nearby stops…" />}
        {nearby.status === "error" && <ErrorState error={nearby.error} onRetry={findNearby} />}
        {nearby.status === "success" &&
          (nearby.data.length === 0 ? (
            <p className="footnote">
              No stops within {NEARBY_RADIUS_M / 1000} km of the map centre.
            </p>
          ) : (
            <ul className="chips-list" aria-label="Nearby stops">
              {nearby.data.map((s) => (
                <li key={s.id}>
                  <button type="button" className="chip-btn" onClick={() => onSelectStop(s.id)}>
                    {s.name} <span className="muted">{Math.round(s.distance_m)} m</span>
                  </button>
                </li>
              ))}
            </ul>
          ))}
      </div>

      {stops.length === 0 ? (
        <EmptyState title="No stops match">Try a different search.</EmptyState>
      ) : (
        <ul className="list" aria-label="All stops">
          {stops.map((s) => {
            const serving = network.servingRoutes.get(s.id) ?? [];
            return (
              <li key={s.id}>
                <button type="button" className="list-row" onClick={() => onSelectStop(s.id)}>
                  <span
                    className={`stop-dot${network.sharedStopIds.has(s.id) ? " is-shared" : ""}`}
                    aria-hidden
                  />
                  <span className="row-main">
                    <span className="row-title">
                      {s.name}
                      {s.id === myStopId && <span className="mine-tag">My stop</span>}
                    </span>
                    <span className="row-sub chips-inline">
                      {s.is_campus_terminal
                        ? "Campus terminal · all routes"
                        : serving.map((r) => <RouteChip key={r} id={r} color={color(r)} />)}
                    </span>
                  </span>
                  {network.sharedStopIds.has(s.id) && <SharedBadge count={serving.length} />}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
