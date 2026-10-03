/**
 * Live fleet occupancy (Feature 8). Polls `GET /buses` — the same backend state the
 * student dashboard reads — so a QR scan shows up here on the next poll. Every
 * number (occupancy, %, seats, QR boardings) is displayed exactly as the backend
 * computed it; nothing is counted or derived in the browser.
 */
import { useCallback, useEffect, useState } from "react";

import type { AdminApi, BusOut, TripBoardingOut } from "./api/client";
import { POLL_MS } from "./polling";
import { ROUTE_LABEL } from "./labels";
import { AlertsPanel, RouteMonitor } from "./RouteMonitor";

export { POLL_MS } from "./polling";

const timeFmt = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function useFleet(api: AdminApi, pollMs = POLL_MS) {
  const [buses, setBuses] = useState<BusOut[] | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const refresh = useCallback(async () => {
    try {
      setBuses(await api.listBuses());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    }
  }, [api]);
  useEffect(() => {
    const first = setTimeout(() => void refresh(), 0);
    const id = setInterval(() => void refresh(), pollMs);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [refresh, pollMs]);
  return { buses, error, refresh };
}

export function FleetOccupancy({ api }: { api: AdminApi }) {
  const { buses, error } = useFleet(api);
  const [tripId, setTripId] = useState<string | null>(null);
  const [busId, setBusId] = useState<string | null>(null);
  const active = (buses ?? []).filter((b) => b.live?.trip_id && b.live.status !== "completed");

  return (
    <div className="layout">
      <section className="card" aria-label="Fleet occupancy">
        <header className="card-head">
          <h2>Live fleet</h2>
          <span className="sim-tag">Synthetic GPS · baseline + simulated QR scans</span>
        </header>
        {error && (
          <p className="error" role="alert">
            {error.message}
          </p>
        )}
        {!buses && !error && <p className="muted">Loading live fleet…</p>}
        {buses && active.length === 0 && <p className="muted">No bus is on an active trip.</p>}
        {active.length > 0 && (
          <table className="fleet">
            <thead>
              <tr>
                <th>Bus</th>
                <th>Trip</th>
                <th>Route status</th>
                <th>Occupancy</th>
                <th>Occupied</th>
                <th>Seats available</th>
                <th>QR boarded</th>
                <th>Last updated</th>
              </tr>
            </thead>
            <tbody>
              {active.map((b) => {
                const l = b.live!;
                const pct = l.occupancy_percentage;
                const tone = pct === null ? "" : pct >= 80 ? "high" : pct >= 60 ? "mid" : "low";
                const rs = l.route_status;
                const rtone =
                  rs === "MAJOR_DEVIATION"
                    ? "major"
                    : rs === "MINOR_DEVIATION"
                      ? "minor"
                      : rs === "NORMAL"
                        ? "ok"
                        : "na";
                return (
                  <tr
                    key={b.id}
                    aria-label={`Bus ${b.id}`}
                    className={busId === b.id || tripId === l.trip_id ? "is-selected" : ""}
                  >
                    <th scope="row">
                      <button
                        type="button"
                        className="link"
                        onClick={() => setBusId(b.id)}
                        aria-label={`Monitor route of BUS ${b.id}`}
                      >
                        BUS {b.id}
                      </button>
                      <span className="sub">{l.route_direction_id}</span>
                    </th>
                    <td>
                      <button
                        type="button"
                        className="link"
                        onClick={() => setTripId(l.trip_id)}
                        aria-label={`Boarding for trip ${l.trip_id}`}
                      >
                        {l.trip_id}
                      </button>
                    </td>
                    <td className={`route-cell route-${rtone}`}>
                      {rs ? (ROUTE_LABEL[rs] ?? rs) : "—"}
                      {(rs === "MINOR_DEVIATION" || rs === "MAJOR_DEVIATION") &&
                        l.deviation_distance_m !== null && (
                          <span className="sub">
                            {Math.round(l.deviation_distance_m)} m off route
                          </span>
                        )}
                    </td>
                    <td className="num">
                      {l.occupancy} / {b.capacity}
                    </td>
                    <td className={`num pct pct-${tone}`}>{pct === null ? "—" : `${pct}%`}</td>
                    <td className="num">{l.available_seats ?? "—"}</td>
                    <td className="num">{l.boarded_count}</td>
                    <td className="num">
                      <time dateTime={l.last_updated}>
                        {timeFmt.format(new Date(l.last_updated))}
                      </time>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="footnote">
          Occupancy = synthetic simulator headcount + QR boardings on the current trip (capped at
          capacity), computed by the backend. Refreshes every {POLL_MS / 1000} s.
        </p>
      </section>
      <div className="side">
        <AlertsPanel api={api} />
        {busId ? (
          <RouteMonitor key={busId} api={api} busId={busId} />
        ) : (
          <section className="card muted" aria-label="Route monitor">
            Select a bus to see its planned route, tracked position and route deviation controls.
          </section>
        )}
        {tripId && <TripBoarding api={api} tripId={tripId} onClose={() => setTripId(null)} />}
      </div>
    </div>
  );
}

function TripBoarding({
  api,
  tripId,
  onClose,
}: {
  api: AdminApi;
  tripId: string;
  onClose: () => void;
}) {
  const [data, setData] = useState<TripBoardingOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api.tripBoarding(tripId).then(
        (d) => !cancelled && (setData(d), setError(null)),
        (e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)),
      );
    void load();
    const id = setInterval(() => void load(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [api, tripId]);
  return (
    <section className="card" aria-label="Trip boarding">
      <header className="card-head">
        <h2>Boarding · {tripId}</h2>
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
      </header>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {data && (
        <>
          <p>
            <strong>{data.total_boarded}</strong> QR boarding{data.total_boarded === 1 ? "" : "s"}{" "}
            on {data.bus_id} ({data.route_direction_id})
          </p>
          {data.events.length === 0 ? (
            <p className="muted">No QR boardings yet.</p>
          ) : (
            <ul className="events" aria-label="Boarding events">
              {data.events.map((e) => (
                <li key={e.boarding_id}>
                  <span>{e.student_id ?? "—"}</span>
                  <span className="muted">at {e.stop_id}</span>
                  <time dateTime={e.timestamp}>{timeFmt.format(new Date(e.timestamp))}</time>
                  {e.scanner === "simulated" && <span className="sim-tag">simulated QR</span>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
