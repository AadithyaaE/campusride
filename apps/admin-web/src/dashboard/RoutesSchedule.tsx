/**
 * Route management, route detail and schedule management (Feature 13) — READ-ONLY.
 * The backend has no route or schedule mutation APIs yet, so there are no edit/save
 * controls. Data: `GET /admin/routes` (aggregates), `GET /routes/{id}` (ordered stops),
 * `GET /admin/schedule` (today's trips) and the shared `/admin/fleet` rows.
 */
import { useState } from "react";

import type { AdminRoute, AdminSchedule, FleetBus, RouteDetail } from "../api/client";
import { busNo, dash, delayText, hm } from "../format";
import { DIRECTION_LABEL } from "../labels";
import { OccupancyCell, OpsBadge, RouteStatusBadge, TripBadge } from "./Badges";

export function RoutesPanel({
  routes,
  error,
  selectedRouteId,
  onSelectRoute,
}: {
  routes: AdminRoute[] | null;
  error: string | null;
  selectedRouteId: string | null;
  onSelectRoute: (routeId: string) => void;
}) {
  return (
    <section className="panel" aria-label="Route management" id="routes">
      <header className="panel-head">
        <h2>Route management</h2>
        <span className="ro-tag">Read-only</span>
      </header>
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
      {routes === null ? (
        !error && <p className="muted">Loading routes…</p>
      ) : routes.length === 0 ? (
        <p className="empty">No routes configured.</p>
      ) : (
        <table className="grid compact" aria-label="Routes table">
          <thead>
            <tr>
              <th>Route</th>
              <th>Directions</th>
              <th className="num">Stops</th>
              <th className="num">Distance</th>
              <th className="num">Active buses</th>
              <th className="num">Trips today</th>
              <th>Issues</th>
            </tr>
          </thead>
          <tbody>
            {routes.map((r) => (
              <tr
                key={r.id}
                aria-label={`Route ${r.id}`}
                className={selectedRouteId === r.id ? "is-selected" : ""}
                onClick={() => onSelectRoute(r.id)}
              >
                <th scope="row">
                  <button
                    type="button"
                    className="route-chip"
                    style={{ ["--route" as string]: r.color }}
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelectRoute(r.id);
                    }}
                    aria-label={`Open route ${r.id}`}
                  >
                    {r.id}
                  </button>
                  <span className="sub">{r.name}</span>
                </th>
                <td>
                  {r.directions.map((d) => (
                    <span key={d.variant_id} className="sub">
                      {d.label}: {d.first_stop.name} → {d.last_stop.name}
                    </span>
                  ))}
                </td>
                <td className="num">{r.directions[0]?.stop_count ?? "—"}</td>
                <td className="num">{r.length_km} km</td>
                <td className="num">
                  {r.active_buses.length}/{r.assigned_buses.length}
                </td>
                <td className="num">
                  {r.trips_today.total}
                  <span className="sub">
                    {r.trips_today.active} active · {r.trips_today.completed} done
                  </span>
                </td>
                <td>
                  {r.delayed_buses.length > 0 && (
                    <span className="badge-ops ops-delayed">{r.delayed_buses.length} delayed</span>
                  )}
                  {r.deviated_buses.length > 0 && (
                    <span className="badge-ops ops-deviated">
                      {r.deviated_buses.length} deviated
                    </span>
                  )}
                  {r.delayed_buses.length === 0 && r.deviated_buses.length === 0 && (
                    <span className="muted small">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function RouteDetailPanel({
  route,
  detail,
  fleet,
  schedule,
  onSelectBus,
  onClose,
}: {
  route: AdminRoute;
  detail: RouteDetail | undefined;
  fleet: FleetBus[];
  schedule: AdminSchedule | null;
  onSelectBus: (busId: string) => void;
  onClose: () => void;
}) {
  const [variant, setVariant] = useState(route.directions[0]?.variant_id ?? "");
  const dir = detail?.directions.find((d) => d.variant_id === variant);
  const buses = fleet.filter((b) => b.route_id === route.id);
  const active = buses.filter((b) => route.active_buses.includes(b.bus_id));
  const delayed = buses.filter((b) => b.is_delayed);
  const deviated = buses.filter(
    (b) => b.route_status === "MINOR_DEVIATION" || b.route_status === "MAJOR_DEVIATION",
  );
  const trips = (schedule?.trips ?? []).filter((t) => t.route_id === route.id);
  return (
    <section className="panel detail" aria-label="Route detail">
      <header className="panel-head">
        <h2>
          <span className="route-chip static" style={{ ["--route" as string]: route.color }}>
            {route.id}
          </span>{" "}
          {route.name}
        </h2>
        <button
          type="button"
          className="btn btn-sm"
          onClick={onClose}
          aria-label="Close route detail"
        >
          Close
        </button>
      </header>
      <dl className="mini-stats">
        <div>
          <dt>Distance</dt>
          <dd>{route.length_km} km</dd>
        </div>
        <div>
          <dt>Active buses</dt>
          <dd>
            {route.active_buses.length}/{route.assigned_buses.length}
          </dd>
        </div>
        <div>
          <dt>Trips today</dt>
          <dd>{route.trips_today.total}</dd>
        </div>
        <div>
          <dt>Avg occupancy</dt>
          <dd>{dash(route.avg_occupancy_percentage, "%")}</dd>
        </div>
        <div>
          <dt>Passengers today</dt>
          <dd>{route.passengers_today}</dd>
        </div>
      </dl>

      <div className="seg" role="tablist" aria-label="Direction">
        {route.directions.map((d) => (
          <button
            key={d.variant_id}
            type="button"
            role="tab"
            aria-selected={variant === d.variant_id}
            onClick={() => setVariant(d.variant_id)}
          >
            {DIRECTION_LABEL[d.direction] ?? d.label} · {d.scheduled_duration_min} min
          </button>
        ))}
      </div>
      {dir ? (
        <ol className="stop-list" aria-label={`Stops ${dir.label}`}>
          {dir.stops.map((s) => (
            <li key={s.stop_id}>
              <span className="stop-seq">{s.seq + 1}</span>
              <span>{s.name}</span>
              <span className="muted small">
                {(s.distance_along_m / 1000).toFixed(1)} km · +
                {Math.round(s.scheduled_offset_s / 60)} min
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted small">Loading stops…</p>
      )}

      <h3>Active buses</h3>
      {active.length === 0 ? (
        <p className="muted small">No bus is running this route now.</p>
      ) : (
        <ul className="ops-list">
          {active.map((b) => (
            <li key={b.bus_id} className="ops-item">
              <button type="button" className="row-link" onClick={() => onSelectBus(b.bus_id)}>
                <strong>Bus {busNo(b.bus_id)}</strong>
                <OpsBadge status={b.operational_status} />
                <span>{b.direction_label}</span>
                <OccupancyCell
                  occupancy={b.occupancy}
                  capacity={b.capacity}
                  pct={b.occupancy_percentage}
                  crowding={b.crowding}
                />
              </button>
            </li>
          ))}
        </ul>
      )}

      <h3>Current delays</h3>
      {delayed.length === 0 ? (
        <p className="muted small">No active delays</p>
      ) : (
        <ul className="ops-list">
          {delayed.map((b) => (
            <li key={b.bus_id} className="ops-item is-late-row">
              Bus {busNo(b.bus_id)} <span className="is-late strong">{delayText(b.delay_min)}</span>{" "}
              · Next: {b.next_stop?.name ?? "—"}
            </li>
          ))}
        </ul>
      )}

      <h3>Route deviations</h3>
      {deviated.length === 0 ? (
        <p className="muted small">No deviations on this route.</p>
      ) : (
        <ul className="ops-list">
          {deviated.map((b) => (
            <li key={b.bus_id} className="ops-item">
              Bus {busNo(b.bus_id)} <RouteStatusBadge status={b.route_status} />{" "}
              {b.deviation_distance_m !== null && `${Math.round(b.deviation_distance_m)} m`}
            </li>
          ))}
        </ul>
      )}

      <h3>Scheduled trips</h3>
      {trips.length === 0 ? (
        <p className="muted small">No trips today.</p>
      ) : (
        <table className="grid compact" aria-label="Route trips">
          <tbody>
            {trips.map((t) => (
              <tr key={t.trip_id}>
                <td className="num">{hm(t.scheduled_departure)}</td>
                <td>{t.direction_label}</td>
                <td>Bus {busNo(t.bus_id)}</td>
                <td>
                  <TripBadge status={t.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function SchedulePanel({
  schedule,
  error,
  onSelectBus,
}: {
  schedule: AdminSchedule | null;
  error: string | null;
  onSelectBus: (busId: string) => void;
}) {
  return (
    <section className="panel" aria-label="Schedule management" id="schedule">
      <header className="panel-head">
        <h2>Schedule · today</h2>
        <span className="ro-tag">Read-only</span>
      </header>
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
      {schedule === null ? (
        !error && <p className="muted">Loading schedule…</p>
      ) : schedule.trips.length === 0 ? (
        <p className="empty">No trips scheduled today.</p>
      ) : (
        <div className="table-wrap tall">
          <table className="grid compact" aria-label="Schedule table">
            <thead>
              <tr>
                <th>Route</th>
                <th>Direction</th>
                <th className="num">Departure</th>
                <th className="num">Arrival</th>
                <th>Bus</th>
                <th>Driver</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {schedule.trips.map((t) => (
                <tr
                  key={t.trip_id}
                  aria-label={`Trip ${t.trip_id}`}
                  className={`trip-row trip-${t.status}`}
                >
                  <td>
                    <span
                      className="route-chip static"
                      style={{ ["--route" as string]: t.route_color }}
                    >
                      {t.route_id}
                    </span>
                  </td>
                  <td>
                    {t.direction_label}
                    <span className="sub">
                      {t.first_stop} → {t.last_stop}
                    </span>
                  </td>
                  <td className="num">
                    {hm(t.scheduled_departure)}
                    {t.actual_start && <span className="sub">actual {hm(t.actual_start)}</span>}
                  </td>
                  <td className="num">
                    {hm(t.scheduled_arrival)}
                    {t.actual_end && <span className="sub">actual {hm(t.actual_end)}</span>}
                  </td>
                  <td>
                    <button type="button" className="bus-id" onClick={() => onSelectBus(t.bus_id)}>
                      {busNo(t.bus_id)}
                    </button>
                    <span className="sub">{t.reg_no}</span>
                  </td>
                  <td>{t.driver?.name ?? "—"}</td>
                  <td>
                    <TripBadge status={t.status} />
                    {t.delay_min !== null && t.delay_min !== 0 && (
                      <span className="sub">{delayText(t.delay_min)}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
