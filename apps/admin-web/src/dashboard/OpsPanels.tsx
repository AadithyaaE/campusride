/**
 * Operational panels (Feature 13) — Active buses, Occupancy, Route deviations, Delays.
 * All four read the SAME shared `/admin/fleet` rows as the table and the map; they only
 * select rows by backend fields (operational status, route status, is_delayed).
 */
import type { FleetBus } from "../api/client";
import { busNo, delayText, etaText } from "../format";
import { ROUTE_LABEL, SEVERITY_TEXT } from "../labels";
import { CrowdingBadge, OccupancyCell, OpsBadge, RouteStatusBadge } from "./Badges";
import { ON_TRIP } from "./fleetFilter";

type Select = (busId: string) => void;

export function ActiveBuses({ rows, onSelectBus }: { rows: FleetBus[]; onSelectBus: Select }) {
  const active = rows.filter((b) => ON_TRIP.has(b.operational_status));
  return (
    <section className="panel" aria-label="Active buses">
      <header className="panel-head">
        <h2>Active buses</h2>
        <span className="count">{active.length}</span>
      </header>
      {active.length === 0 ? (
        <p className="empty">No bus is on a running trip.</p>
      ) : (
        <ul className="bus-cards">
          {active.map((b) => (
            <li key={b.bus_id}>
              <button
                type="button"
                className={`bus-card row-${b.operational_status}`}
                onClick={() => onSelectBus(b.bus_id)}
                aria-label={`Active BUS ${b.bus_id}`}
              >
                <span className="bus-card-head">
                  <strong>BUS {busNo(b.bus_id)}</strong>
                  <OpsBadge status={b.operational_status} />
                </span>
                <span className="route-line" style={{ ["--route" as string]: b.route_color }}>
                  {b.route_id} · {b.route_name}
                </span>
                <span className="kv">
                  <span>{b.speed_kmh ?? "—"} km/h</span>
                  <span>
                    {b.occupancy ?? "—"}/{b.capacity}
                  </span>
                </span>
                <span className="kv">
                  <span>Next: {b.next_stop?.name ?? "—"}</span>
                </span>
                <span className="kv">
                  <span>ETA: {etaText(b.eta_next_stop_min, b.eta_status)}</span>
                  {b.is_delayed && <span className="is-late">{delayText(b.delay_min)}</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function OccupancyPanel({ rows, onSelectBus }: { rows: FleetBus[]; onSelectBus: Select }) {
  const onTrip = rows
    .filter((b) => ON_TRIP.has(b.operational_status) && b.occupancy !== null)
    .sort((a, b) => (b.occupancy_percentage ?? -1) - (a.occupancy_percentage ?? -1));
  return (
    <section className="panel" aria-label="Occupancy">
      <header className="panel-head">
        <h2>Occupancy</h2>
        <span className="legend small">
          <span className="crowd-key crowd-low">Low &lt;60%</span>
          <span className="crowd-key crowd-mid">Medium 60–79%</span>
          <span className="crowd-key crowd-high">High ≥80%</span>
        </span>
      </header>
      {onTrip.length === 0 ? (
        <p className="empty">No bus is carrying passengers right now.</p>
      ) : (
        <table className="grid compact" aria-label="Occupancy table">
          <thead>
            <tr>
              <th>Bus</th>
              <th>Route</th>
              <th>Load</th>
              <th className="num">Seats free</th>
              <th>Crowding</th>
            </tr>
          </thead>
          <tbody>
            {onTrip.map((b) => (
              <tr key={b.bus_id} aria-label={`Occupancy BUS ${b.bus_id}`}>
                <th scope="row">
                  <button type="button" className="bus-id" onClick={() => onSelectBus(b.bus_id)}>
                    {busNo(b.bus_id)}
                  </button>
                </th>
                <td>{b.route_id}</td>
                <td>
                  <OccupancyCell
                    occupancy={b.occupancy}
                    capacity={b.capacity}
                    pct={b.occupancy_percentage}
                    crowding={b.crowding}
                  />
                </td>
                <td className="num">{b.available_seats ?? "—"}</td>
                <td>
                  <CrowdingBadge crowding={b.crowding} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="footnote">
        Feature 8 occupancy: synthetic headcount + QR boardings, computed by the backend.
      </p>
    </section>
  );
}

const TALLY = ["NORMAL", "MINOR_DEVIATION", "MAJOR_DEVIATION"] as const;

export function DeviationsPanel({ rows, onSelectBus }: { rows: FleetBus[]; onSelectBus: Select }) {
  const deviated = rows
    .filter((b) => b.route_status === "MINOR_DEVIATION" || b.route_status === "MAJOR_DEVIATION")
    .sort((a, b) => (b.deviation_distance_m ?? 0) - (a.deviation_distance_m ?? 0));
  return (
    <section className="panel" aria-label="Route deviations">
      <header className="panel-head">
        <h2>Route deviations</h2>
      </header>
      <dl className="tally" aria-label="Route status counts">
        {TALLY.map((k) => (
          <div key={k} className={`tally-${k.toLowerCase()}`}>
            <dt>{ROUTE_LABEL[k]}</dt>
            <dd>{rows.filter((b) => b.route_status === k).length}</dd>
          </div>
        ))}
      </dl>
      {deviated.length === 0 ? (
        <p className="empty">All tracked buses are on their planned routes.</p>
      ) : (
        <ul className="ops-list">
          {deviated.map((b) => {
            const alert = b.active_alerts.find((a) => a.type === "ROUTE_DEVIATION");
            const major = b.route_status === "MAJOR_DEVIATION";
            return (
              <li key={b.bus_id} className={`ops-item ${major ? "is-major" : "is-minor"}`}>
                <button
                  type="button"
                  className="row-link"
                  onClick={() => onSelectBus(b.bus_id)}
                  aria-label={`Focus BUS ${b.bus_id} on map`}
                >
                  <strong>Bus {busNo(b.bus_id)}</strong>
                  <span>{b.route_id}</span>
                  <RouteStatusBadge status={b.route_status} />
                  <span className="num strong">
                    {b.deviation_distance_m === null
                      ? "—"
                      : `${Math.round(b.deviation_distance_m)} m`}
                  </span>
                </button>
                {alert && (
                  <span className={`sev-tag sev-${alert.severity}`}>
                    {SEVERITY_TEXT[alert.severity] ?? alert.severity} alert active
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export function DelaysPanel({ rows, onSelectBus }: { rows: FleetBus[]; onSelectBus: Select }) {
  const delayed = rows
    .filter((b) => b.is_delayed)
    .sort((a, b) => (b.delay_s ?? 0) - (a.delay_s ?? 0));
  return (
    <section className="panel" aria-label="Delays">
      <header className="panel-head">
        <h2>Delays</h2>
        <span className="count">{delayed.length}</span>
      </header>
      {delayed.length === 0 ? (
        <p className="empty">No active delays</p>
      ) : (
        <ul className="ops-list">
          {delayed.map((b) => (
            <li key={b.bus_id} className="ops-item is-late-row">
              <button
                type="button"
                className="row-link"
                onClick={() => onSelectBus(b.bus_id)}
                aria-label={`Delayed BUS ${b.bus_id}`}
              >
                <strong>Bus {busNo(b.bus_id)}</strong>
                <span>{b.route_id}</span>
                <span className="is-late strong">{delayText(b.delay_min)}</span>
                <OpsBadge status={b.operational_status} />
              </button>
              <span className="sub">
                {b.current_stop?.name ?? "—"} → Next: {b.next_stop?.name ?? "—"}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="footnote">Backend delay rule: ≥ 5 min behind the timetable while running.</p>
    </section>
  );
}
