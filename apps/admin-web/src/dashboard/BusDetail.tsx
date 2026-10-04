/**
 * Bus detail (Feature 13): one `/admin/fleet` row in full, plus the existing Feature 10
 * route monitor (planned route vs. tracked position, demo controls) and the Feature 8
 * trip boarding list. Every value is the backend's.
 */
import { type ReactNode, useState } from "react";

import type { AdminApi, AlertOut, FleetBus } from "../api/client";
import { ageText, busNo, dash, delayText, etaText, hms } from "../format";
import { DIRECTION_LABEL, SEVERITY_TEXT, TRIP_LABEL } from "../labels";
import { RouteMonitor } from "../RouteMonitor";
import { TripBoarding } from "../TripBoarding";
import { CrowdingBadge, GpsBadge, OpsBadge, RouteStatusBadge } from "./Badges";

export function BusDetail({
  api,
  bus,
  alerts,
  onClose,
  onSelectRoute,
}: {
  api: AdminApi;
  bus: FleetBus;
  /** Shared active alerts (full messages) — those of this bus are listed. */
  alerts: AlertOut[] | null;
  onClose: () => void;
  onSelectRoute: (routeId: string) => void;
}) {
  const [showBoarding, setShowBoarding] = useState(false);
  const mine = (alerts ?? []).filter((a) => a.bus_id === bus.bus_id);
  const rows: [string, ReactNode][] = [
    ["Registration", bus.reg_no],
    [
      "Route",
      <button key="r" type="button" className="link" onClick={() => onSelectRoute(bus.route_id)}>
        {bus.route_id} · {bus.route_name}
      </button>,
    ],
    [
      "Direction",
      bus.direction_label ?? (bus.direction ? DIRECTION_LABEL[bus.direction] : null) ?? "—",
    ],
    ["Driver", bus.driver ? `${bus.driver.name} (${bus.driver.id})` : "—"],
    [
      "Trip",
      bus.trip_id ? (
        <>
          {bus.trip_id}{" "}
          {bus.trip_status && (
            <span className="muted">· {TRIP_LABEL[bus.trip_status] ?? bus.trip_status}</span>
          )}
        </>
      ) : (
        "—"
      ),
    ],
    ["Speed", dash(bus.speed_kmh, " km/h")],
    ["Current stop", bus.current_stop?.name ?? "—"],
    ["Next stop", bus.next_stop?.name ?? "—"],
    [
      "ETA (next stop)",
      <>
        {etaText(bus.eta_next_stop_min, bus.eta_status)}
        {bus.eta_confidence && <span className="muted"> · {bus.eta_confidence} confidence</span>}
      </>,
    ],
    [
      "Occupancy",
      bus.occupancy === null ? (
        "—"
      ) : (
        <>
          {bus.occupancy}/{bus.capacity} · {dash(bus.occupancy_percentage, "%")} ·{" "}
          {dash(bus.available_seats)} seats free <CrowdingBadge crowding={bus.crowding} />
        </>
      ),
    ],
    ["QR boarded", String(bus.boarded_count)],
    [
      "Delay",
      <span key="d" className={bus.is_delayed ? "is-late strong" : ""}>
        {delayText(bus.delay_min)}
      </span>,
    ],
    ["Route status", <RouteStatusBadge key="rs" status={bus.route_status} />],
    [
      "Deviation",
      bus.deviation_distance_m === null
        ? "—"
        : `${Math.round(bus.deviation_distance_m)} m from planned route`,
    ],
    [
      "GPS",
      <>
        <GpsBadge gps={bus.gps} /> {ageText(bus.gps_age_s)}
        <span className="muted"> · fix {hms(bus.last_updated)}</span>
      </>,
    ],
    ["Source", bus.source === "sim" ? "Synthetic simulator" : "Driver device"],
  ];
  return (
    <section className="panel detail" aria-label="Bus detail">
      <header className="panel-head">
        <h2>
          BUS {busNo(bus.bus_id)} <OpsBadge status={bus.operational_status} />
        </h2>
        <button
          type="button"
          className="btn btn-sm"
          onClick={onClose}
          aria-label="Close bus detail"
        >
          Close
        </button>
      </header>
      <dl className="kv-grid">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <div className="detail-alerts" aria-label="Bus alerts">
        <h3>Active alerts</h3>
        {mine.length === 0 ? (
          <p className="muted small">None for this bus.</p>
        ) : (
          <ul className="summary-list">
            {mine.map((a) => (
              <li key={a.alert_id} className={`sev-row sev-${a.severity}`}>
                <span className={`sev-tag sev-${a.severity}`}>
                  {SEVERITY_TEXT[a.severity] ?? a.severity}
                </span>
                <span>{a.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {bus.trip_id && (
        <div className="controls">
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setShowBoarding((v) => !v)}
            aria-label={`Boarding for trip ${bus.trip_id}`}
          >
            {showBoarding ? "Hide boarding" : "QR boarding events"}
          </button>
        </div>
      )}
      {showBoarding && bus.trip_id && (
        <TripBoarding api={api} tripId={bus.trip_id} onClose={() => setShowBoarding(false)} />
      )}
      <RouteMonitor key={bus.bus_id} api={api} busId={bus.bus_id} />
    </section>
  );
}
