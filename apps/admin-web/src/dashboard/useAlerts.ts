/** Active fleet alerts (Feature 11), polled once and shared across the control room. */
import { useCallback, useState } from "react";

import type { AdminApi, AlertOut } from "../api/client";
import { POLL_MS } from "../polling";
import { usePoll } from "../usePoll";

export interface AlertsState {
  alerts: AlertOut[] | null;
  error: string | null;
  markRead: (alertId: string) => void;
  /** Re-fetch the active alerts once (e.g. after a WebSocket reconnect). */
  refresh: () => Promise<void>;
  /** Apply a pushed alert event (Feature 14) — the backend's alert, as sent. */
  apply: (
    kind: "created" | "updated" | "resolved" | "read",
    alert: Partial<AlertOut> & { alert_id: string },
  ) => void;
}

export const fleetOnly = (a: AlertOut[]) => a.filter((x) => x.recipient === "admin");

/** Active fleet alerts, polled every POLL_MS, with optimistic mark-read. */
export function useAlerts(api: AdminApi, intervalMs: number | null = POLL_MS): AlertsState {
  const load = useCallback(() => api.alerts(true).then(fleetOnly), [api]);
  const polled = usePoll(load, intervalMs);
  const { mutate } = polled;
  const apply: AlertsState["apply"] = useCallback(
    (kind, alert) =>
      mutate((prev) => {
        const list = prev ?? [];
        if (kind === "read") {
          return list.map((a) => (a.alert_id === alert.alert_id ? { ...a, read: true } : a));
        }
        if (kind === "resolved") return list.filter((a) => a.alert_id !== alert.alert_id);
        const full = alert as AlertOut;
        if (full.recipient !== "admin" || !full.active) return list;
        const rest = list.filter((a) => a.alert_id !== full.alert_id);
        return [full, ...rest].sort((a, b) => b.timestamp.localeCompare(a.timestamp));
      }),
    [mutate],
  );
  const [readLocally, setReadLocally] = useState<ReadonlySet<string>>(new Set());
  const markRead = (alertId: string) => {
    setReadLocally((prev) => new Set(prev).add(alertId));
    api.markAlertRead(alertId).then(
      () => void polled.refresh(),
      () => {
        setReadLocally((prev) => {
          const next = new Set(prev);
          next.delete(alertId);
          return next;
        });
      },
    );
  };
  const alerts =
    polled.data?.map((a) => (readLocally.has(a.alert_id) ? { ...a, read: true } : a)) ?? null;
  return { alerts, error: polled.error, markRead, refresh: polled.refresh, apply };
}
