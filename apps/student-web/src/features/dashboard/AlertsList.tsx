/**
 * Notifications (Feature 11) — the student's OWN in-app alerts from `GET /alerts`.
 *
 * Every alert is created, deduplicated and resolved by the backend AlertService; this
 * panel only displays them and lets the student mark one read (`PATCH /alerts/{id}/read`).
 * Delivered by HTTP polling for now; the same backend events can later arrive over
 * WebSockets without changing what is shown here.
 */
import type { Alert, AlertSeverity, AlertType } from "../../api/types";
import { Icon, type IconName } from "../../components/Icon";
import { EmptyState } from "../../components/StateViews";
import { ago } from "../../lib/timeago";

const ICON: Record<AlertType, IconName> = {
  BUS_APPROACHING: "bus",
  BUS_DELAYED: "clock",
  CAPACITY_WARNING: "users",
  ROUTE_DEVIATION: "route",
  MISSED_BUS: "clock",
  ALTERNATIVE_BUS_AVAILABLE: "bus",
  BREAKDOWN: "alert",
  BROADCAST: "bell",
};

/** Friendly headings for the backend alert types (the message itself comes from the backend). */
const TITLE: Record<AlertType, string> = {
  BUS_APPROACHING: "Your bus is approaching",
  BUS_DELAYED: "Your bus is delayed",
  CAPACITY_WARNING: "Your bus is filling up",
  ROUTE_DEVIATION: "Your bus left its planned route",
  MISSED_BUS: "You missed your bus",
  ALTERNATIVE_BUS_AVAILABLE: "Another bus can get you there",
  BREAKDOWN: "Your bus has a problem",
  BROADCAST: "Transport office notice",
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
      </header>
      {alerts.length === 0 ? (
        <EmptyState title="You're all caught up">
          New updates about your bus will appear here.
        </EmptyState>
      ) : (
        <ul className="alerts" aria-label="Alert list">
          {alerts.map((a) => (
            <li
              key={a.alert_id}
              className={`alert alert-${a.severity}${a.read ? " is-read" : " is-unread"}${
                a.active ? "" : " is-resolved"
              }`}
              aria-label={`${TITLE[a.type] ?? a.title}${a.read ? "" : " (unread)"}`}
            >
              <span className="alert-icon" aria-hidden="true">
                <Icon name={ICON[a.type] ?? "bell"} size={18} />
              </span>
              <span className="row-main">
                <strong className="alert-title">
                  {TITLE[a.type] ?? a.title}
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
                  aria-label={`Mark ${TITLE[a.type] ?? a.title} read`}
                >
                  Mark read
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
