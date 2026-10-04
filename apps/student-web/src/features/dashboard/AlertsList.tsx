/**
 * Notifications (Feature 11) — the student's OWN in-app alerts from `GET /alerts`.
 *
 * Every alert is created, deduplicated and resolved by the backend AlertService; this
 * panel only displays them and lets the student mark one read (`PATCH /alerts/{id}/read`).
 * Delivered by HTTP polling for now; the same backend events can later arrive over
 * WebSockets without changing what is shown here.
 */
import type { Alert, AlertSeverity, AlertType } from "../../api/types";
import { EmptyState } from "../../components/StateViews";
import { ago } from "../../lib/timeago";
import { SimTag } from "./LiveCards";

const ICON: Record<AlertType, string> = {
  BUS_APPROACHING: "🚌",
  BUS_DELAYED: "⏱",
  CAPACITY_WARNING: "👥",
  ROUTE_DEVIATION: "🛣",
  MISSED_BUS: "⏰",
  ALTERNATIVE_BUS_AVAILABLE: "🔄",
  BREAKDOWN: "⚠",
  BROADCAST: "📣",
};

const SEVERITY_LABEL: Record<AlertSeverity, string> = {
  info: "Info",
  warning: "Warning",
  critical: "Critical",
};

interface Props {
  alerts: Alert[];
  /** Current simulation time, for "N min ago". */
  nowIso: string | null;
  onMarkRead: (alertId: string) => void;
}

export function AlertsList({ alerts, nowIso, onMarkRead }: Props) {
  const unread = alerts.filter((a) => !a.read).length;
  return (
    <section id="alerts" aria-label="Notifications">
      <header className="section-head">
        <h3 className="section-title">
          Notifications{" "}
          {unread > 0 && (
            <span className="unread-count" aria-label={`${unread} unread`}>
              {unread}
            </span>
          )}
        </h3>
        <SimTag />
      </header>
      {alerts.length === 0 ? (
        <EmptyState title="No notifications yet" />
      ) : (
        <ul className="alerts" aria-label="Alert list">
          {alerts.map((a) => (
            <li
              key={a.alert_id}
              className={`alert alert-${a.severity}${a.read ? " is-read" : " is-unread"}${
                a.active ? "" : " is-resolved"
              }`}
              aria-label={`${a.title}${a.read ? "" : " (unread)"}`}
            >
              <span className="alert-icon" aria-hidden="true">
                {ICON[a.type] ?? "•"}
              </span>
              <span className="row-main">
                <strong className="alert-title">
                  {a.title}
                  <span className="alert-severity">{SEVERITY_LABEL[a.severity]}</span>
                  {!a.active && <span className="alert-severity">Resolved</span>}
                </strong>
                <span className="row-sub">{a.message}</span>
                <time className="alert-time" dateTime={a.timestamp}>
                  {ago(a.timestamp, nowIso)}
                </time>
              </span>
              {!a.read && (
                <button
                  type="button"
                  className="link-button alert-read"
                  onClick={() => onMarkRead(a.alert_id)}
                  aria-label={`Mark ${a.title} read`}
                >
                  Mark read
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="footnote">
        In-app notifications from the backend about your college-assigned bus (simulated data).
      </p>
    </section>
  );
}
