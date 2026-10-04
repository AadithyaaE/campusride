/** QR boarding events of one trip (Feature 8) — admins see every event. Polled while open. */
import { useEffect, useState } from "react";

import type { AdminApi, TripBoardingOut } from "./api/client";
import { timeFmt } from "./format";
import { POLL_MS } from "./polling";

export function TripBoarding({
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
    <section className="subpanel" aria-label="Trip boarding">
      <header className="panel-head">
        <h3>Boarding · {tripId}</h3>
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
