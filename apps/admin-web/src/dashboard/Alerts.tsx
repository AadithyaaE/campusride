/**
 * Fleet alerts (Feature 11) in the control room. Alerts are created, refreshed and
 * resolved by the backend AlertService; the dashboard only lists them and marks them
 * read (`PATCH /alerts/{id}/read`). Active alerts are polled ONCE (`useAlerts`) and
 * shared by the top summary, the alert list and the bus detail panel.
 */
import { useCallback, useState } from "react";

import type { AdminApi, AlertOut } from "../api/client";
import { hms } from "../format";
import { SEVERITY_TEXT } from "../labels";
import { POLL_MS } from "../polling";
import { usePoll } from "../usePoll";
import { type AlertsState, fleetOnly, useAlerts } from "./useAlerts";

const ALERT_ICON: Record<string, string> = {
  ROUTE_DEVIATION: "🛣",
  BUS_DELAYED: "⏱",
  CAPACITY_WARNING: "👥",
  BREAKDOWN: "⚠",
};
const SEVERITY_ORDER: Record<string, number> = { critical: 0, warning: 1, info: 2 };

/** Compact strip near the top: count + the most severe active alerts. */
export function AlertSummary({
  alerts,
  onSelectBus,
}: {
  alerts: AlertOut[] | null;
  onSelectBus: (busId: string) => void;
}) {
  const list = [...(alerts ?? [])].sort(
    (a, b) =>
      (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9) ||
      b.timestamp.localeCompare(a.timestamp),
  );
  return (
    <section className="panel alert-summary" aria-label="Alert summary">
      <header className="panel-head">
        <h2>
          <span className="big-num">{alerts === null ? "…" : list.length}</span> Active alert
          {list.length === 1 ? "" : "s"}
        </h2>
        <a href="#alerts" className="link small">
          All alerts
        </a>
      </header>
      {alerts !== null && list.length === 0 && <p className="muted small">No active alerts.</p>}
      <ul className="summary-list">
        {list.slice(0, 3).map((a) => (
          <li key={a.alert_id} className={`sev-row sev-${a.severity}`}>
            <span className={`sev-tag sev-${a.severity}`}>
              {SEVERITY_TEXT[a.severity] ?? a.severity}
            </span>
            {a.bus_id ? (
              <button type="button" className="row-link" onClick={() => onSelectBus(a.bus_id!)}>
                {a.message}
              </button>
            ) : (
              <span>{a.message}</span>
            )}
          </li>
        ))}
      </ul>
      {list.length > 3 && <p className="muted small">+{list.length - 3} more</p>}
    </section>
  );
}

function AlertItem({ a, onRead }: { a: AlertOut; onRead?: (id: string) => void }) {
  return (
    <li
      className={`alert alert-${a.severity}${a.read ? " is-read" : " is-unread"}${a.active ? "" : " is-resolved"}`}
      aria-label={`${a.title}${a.read ? "" : " (unread)"}`}
    >
      <strong>
        <span aria-hidden="true">{ALERT_ICON[a.type] ?? "•"} </span>
        {a.title}
        <span className="sev">{SEVERITY_TEXT[a.severity] ?? a.severity}</span>
        <span className={`state ${a.active ? "state-active" : "state-resolved"}`}>
          {a.active ? "Active" : "Resolved"}
        </span>
      </strong>
      <span>{a.message}</span>
      <span className="alert-foot">
        <span className="muted">
          {a.bus_id ? `Bus ${a.bus_id}` : "Fleet"}
          {a.route_id ? ` · ${a.route_id}` : ""} ·{" "}
          <time dateTime={a.timestamp}>{hms(a.timestamp)}</time>
          {!a.active && a.resolved_at && <> · resolved {hms(a.resolved_at)}</>}
          {" · "}
          {a.read ? "Read" : "Unread"}
        </span>
        {!a.read && onRead && (
          <button
            type="button"
            className="link"
            onClick={() => onRead(a.alert_id)}
            aria-label={`Mark ${a.title} for ${a.bus_id ?? "fleet"} read`}
          >
            Mark read
          </button>
        )}
      </span>
    </li>
  );
}

/** Standalone alert panel that polls on its own (the control room passes shared state instead). */
export function AlertsPanel({ api }: { api: AdminApi }) {
  return <AlertsList api={api} state={useAlerts(api)} />;
}

/** Full alert list: active (shared poll) or resolved (fetched only while that tab is open). */
export function AlertsList({ api, state }: { api: AdminApi; state: AlertsState }) {
  const { alerts, error, markRead } = state;
  const [tab, setTab] = useState<"active" | "resolved">("active");
  const unread = (alerts ?? []).filter((a) => !a.read).length;
  return (
    <section className="panel" aria-label="Active alerts" id="alerts">
      <header className="panel-head">
        <h2>
          Alerts{" "}
          {unread > 0 && (
            <span className="badge" aria-label={`${unread} unread`}>
              {unread}
            </span>
          )}
        </h2>
        <div className="seg" role="tablist" aria-label="Alert list">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "active"}
            onClick={() => setTab("active")}
          >
            Active
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "resolved"}
            onClick={() => setTab("resolved")}
          >
            Resolved
          </button>
        </div>
      </header>
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
      {tab === "active" ? (
        alerts === null ? (
          <p className="muted">Loading…</p>
        ) : alerts.length === 0 ? (
          <p className="muted">No active alerts.</p>
        ) : (
          <ul className="alerts" aria-label="Alert list">
            {alerts.map((a) => (
              <AlertItem key={a.alert_id} a={a} onRead={markRead} />
            ))}
          </ul>
        )
      ) : (
        <ResolvedAlerts api={api} />
      )}
      <p className="footnote">
        Raised and resolved by the backend on state changes — delay, capacity and major route
        deviation. Pushed in real time; REST keeps it in sync.
      </p>
    </section>
  );
}

function ResolvedAlerts({ api }: { api: AdminApi }) {
  const load = useCallback(() => api.alerts(false).then(fleetOnly), [api]);
  const { data, error } = usePoll(load, POLL_MS * 5);
  if (error)
    return (
      <p className="error small" role="alert">
        {error}
      </p>
    );
  if (data === null) return <p className="muted">Loading…</p>;
  if (data.length === 0) return <p className="muted">No resolved alerts yet.</p>;
  return (
    <ul className="alerts" aria-label="Resolved alerts">
      {data.map((a) => (
        <AlertItem key={a.alert_id} a={a} />
      ))}
    </ul>
  );
}
