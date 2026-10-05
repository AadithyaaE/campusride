/**
 * RECENT COMMUTES (Feature 16) — `GET /students/me/history`, derived by the backend from
 * stored trips, boarding events and missed-bus alerts. Re-fetched only when today's commute
 * changes (phase / trip status / boarding), never on a timer.
 */
import { useEffect, useState } from "react";

import { useApi } from "../../api/ApiContext";
import type { CommuteHistoryEntry } from "../../api/types";
import { formatClock } from "../../lib/format";

const OUTCOME: Record<CommuteHistoryEntry["outcome"], { label: string; tone: string }> = {
  boarded: { label: "Boarded", tone: "ok" },
  in_progress: { label: "In progress", tone: "info" },
  missed: { label: "Missed", tone: "bad" },
  ended_early: { label: "Trip ended early", tone: "warn" },
  no_boarding_recorded: { label: "No boarding recorded", tone: "muted" },
  cancelled: { label: "Cancelled", tone: "muted" },
};

const dayFmt = new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  day: "numeric",
  month: "short",
});

export function RecentCommutes({ refreshKey }: { refreshKey: string }) {
  const api = useApi();
  const [entries, setEntries] = useState<CommuteHistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.myHistory(10).then(
      (h) => {
        if (!cancelled) {
          setEntries(h.entries);
          setError(null);
        }
      },
      (e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)),
    );
    return () => {
      cancelled = true;
    };
  }, [api, refreshKey]);

  return (
    <section className="recent-commutes" aria-label="Recent commutes">
      <h3 className="section-title">Recent commutes</h3>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {entries === null && !error && <p className="muted">Getting your recent commutes…</p>}
      {entries !== null && entries.length === 0 && (
        <p className="muted">No recent commutes yet. Your trips appear here after your bus runs.</p>
      )}
      {entries !== null && entries.length > 0 && (
        <ul className="history-list">
          {entries.map((e) => {
            const o = OUTCOME[e.outcome];
            return (
              <li key={e.trip_id} className="history-item" aria-label={`Commute ${e.trip_id}`}>
                <div className="history-head">
                  <strong>{dayFmt.format(new Date(`${e.service_date}T12:00:00`))}</strong>
                  <span className={`phase-badge phase-${o.tone}`}>{o.label}</span>
                </div>
                <p className="history-line">
                  BUS {e.bus_id} · {e.direction_label ?? e.route_direction_id}
                  {e.boarding_stop && <> · {e.boarding_stop.name}</>}
                </p>
                <p className="history-line muted">
                  Departed {formatClock(e.actual_start ?? e.scheduled_departure)}
                  {e.boarding_time && <> · boarded {formatClock(e.boarding_time)}</>}
                  {e.scanner === "simulated" && <> · demo QR scan</>}
                  {e.end_reason === "driver_stop" && <> · ended early by the driver</>}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
