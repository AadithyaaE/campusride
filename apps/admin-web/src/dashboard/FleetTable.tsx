/**
 * Live fleet table + filters (Feature 13). Rows are `GET /admin/fleet` exactly as the
 * backend computed them — ETA (Feature 5), occupancy (Feature 8), route status
 * (Feature 10), delay (tracking). Filter options come from the same response.
 */
import type { AdminFleet, FleetBus } from "../api/client";
import { ageText, busNo, dash, delayText, etaText } from "../format";
import { DIRECTION_LABEL, OPS_LABEL } from "../labels";
import { OccupancyCell, OpsBadge, RouteStatusBadge } from "./Badges";
import { type FleetFilter, isFiltered, NO_FILTER } from "./fleetFilter";

export function FleetFilters({
  fleet,
  filter,
  onChange,
}: {
  fleet: AdminFleet | null;
  filter: FleetFilter;
  onChange: (f: FleetFilter) => void;
}) {
  const opts = fleet?.options;
  return (
    <div className="filters" role="group" aria-label="Fleet filters">
      <label>
        Route
        <select
          value={filter.route}
          onChange={(e) => onChange({ ...filter, route: e.target.value })}
          aria-label="Route filter"
        >
          <option value="">All routes</option>
          {opts?.routes.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Bus
        <select
          value={filter.bus}
          onChange={(e) => onChange({ ...filter, bus: e.target.value })}
          aria-label="Bus filter"
        >
          <option value="">All buses</option>
          {opts?.buses.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Status
        <select
          value={filter.status}
          onChange={(e) => onChange({ ...filter, status: e.target.value })}
          aria-label="Status filter"
        >
          <option value="">All status</option>
          {opts?.statuses.map((o) => (
            <option key={o.value} value={o.value}>
              {OPS_LABEL[o.value] ?? o.label}
            </option>
          ))}
        </select>
      </label>
      {isFiltered(filter) && (
        <button type="button" className="btn btn-sm" onClick={() => onChange(NO_FILTER)}>
          Clear filters
        </button>
      )}
    </div>
  );
}

export function FleetTable({
  rows,
  total,
  selectedBusId,
  onSelectBus,
  onSelectRoute,
}: {
  rows: FleetBus[];
  total: number;
  selectedBusId: string | null;
  onSelectBus: (busId: string) => void;
  onSelectRoute: (routeId: string) => void;
}) {
  if (rows.length === 0) {
    return (
      <p className="empty">
        {total === 0 ? "No buses in the fleet." : "No buses match the current filters."}
      </p>
    );
  }
  return (
    <div className="table-wrap">
      <table className="grid fleet-table" aria-label="Fleet table">
        <thead>
          <tr>
            <th>Bus</th>
            <th>Route</th>
            <th>Status</th>
            <th className="num">Speed</th>
            <th>Current → Next stop</th>
            <th className="num">ETA</th>
            <th className="num">Delay</th>
            <th>Occupancy</th>
            <th>Route status</th>
            <th>Driver</th>
            <th>Alerts</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((b) => (
            <tr
              key={b.bus_id}
              aria-label={`Bus ${b.bus_id}`}
              className={`${selectedBusId === b.bus_id ? "is-selected" : ""} row-${b.operational_status}`}
              onClick={() => onSelectBus(b.bus_id)}
            >
              <th scope="row">
                <button
                  type="button"
                  className="bus-id"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectBus(b.bus_id);
                  }}
                  aria-label={`Open BUS ${b.bus_id}`}
                >
                  {busNo(b.bus_id)}
                </button>
              </th>
              <td>
                <button
                  type="button"
                  className="route-chip"
                  style={{ ["--route" as string]: b.route_color }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectRoute(b.route_id);
                  }}
                  aria-label={`Open route ${b.route_id}`}
                >
                  {b.route_id}
                </button>
                <span className="sub">
                  {b.direction ? (DIRECTION_LABEL[b.direction] ?? b.direction) : b.route_name}
                </span>
              </td>
              <td>
                <OpsBadge status={b.operational_status} />
              </td>
              <td className="num">{dash(b.speed_kmh, " km/h")}</td>
              <td className="stops">
                <span>{b.current_stop?.name ?? "—"}</span>
                <span className="sub">→ {b.next_stop?.name ?? "—"}</span>
              </td>
              <td className="num">{etaText(b.eta_next_stop_min, b.eta_status)}</td>
              <td className={`num${b.is_delayed ? " is-late" : ""}`}>{delayText(b.delay_min)}</td>
              <td>
                <OccupancyCell
                  occupancy={b.occupancy}
                  capacity={b.capacity}
                  pct={b.occupancy_percentage}
                  crowding={b.crowding}
                />
              </td>
              <td>
                <RouteStatusBadge status={b.route_status} />
                {(b.route_status === "MINOR_DEVIATION" || b.route_status === "MAJOR_DEVIATION") &&
                  b.deviation_distance_m !== null && (
                    <span className="sub">{Math.round(b.deviation_distance_m)} m off route</span>
                  )}
              </td>
              <td className="driver-cell">
                {b.driver?.name ?? "—"}
                {b.gps !== "LIVE" && (
                  <span className={`sub gps-${b.gps.toLowerCase()}`}>
                    {b.gps === "STALE" ? `GPS stale · ${ageText(b.gps_age_s)}` : "No GPS yet"}
                  </span>
                )}
              </td>
              <td>
                {b.active_alerts.length === 0 ? (
                  <span className="muted">—</span>
                ) : (
                  <span
                    className={`alert-count sev-${
                      b.active_alerts.some((a) => a.severity === "critical")
                        ? "critical"
                        : "warning"
                    }`}
                    title={b.active_alerts.map((a) => a.message).join(" · ")}
                    aria-label={`${b.active_alerts.length} active alert${b.active_alerts.length === 1 ? "" : "s"}`}
                  >
                    {b.active_alerts.length}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
