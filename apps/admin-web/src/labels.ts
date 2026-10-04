/** Display labels for backend statuses. Labels only — no logic. */
export const ROUTE_LABEL: Record<string, string> = {
  NORMAL: "Normal",
  MINOR_DEVIATION: "Minor deviation",
  MAJOR_DEVIATION: "Major deviation",
  NO_ACTIVE_TRIP: "No active trip",
  NO_ROUTE: "No route",
  NO_LIVE_DATA: "No live data",
  STALE: "Live data stale",
  INVALID_LOCATION: "Invalid location",
};

/** Tone class for a backend route status (Feature 10). */
export function routeTone(status: string | null | undefined): "ok" | "minor" | "major" | "na" {
  return status === "MAJOR_DEVIATION"
    ? "major"
    : status === "MINOR_DEVIATION"
      ? "minor"
      : status === "NORMAL"
        ? "ok"
        : "na";
}

/** Backend operational status (Feature 13, `admin_service.operational_status`). */
export const OPS_LABEL: Record<string, string> = {
  active: "Active",
  delayed: "Delayed",
  deviated: "Deviated",
  breakdown: "Breakdown",
  waiting: "Waiting",
  completed: "Completed",
  idle: "Idle",
  out_of_service: "Out of service",
};

export const TRIP_LABEL: Record<string, string> = {
  scheduled: "Scheduled",
  active: "Active",
  completed: "Completed",
  cancelled: "Cancelled",
};

export const DIRECTION_LABEL: Record<string, string> = {
  to_campus: "To campus",
  from_campus: "From campus",
};

/** Crowding band as the backend returned it (Feature 6/8: <60 Low · 60–79 Medium · ≥80 High). */
export const CROWDING_TONE: Record<string, string> = {
  Low: "low",
  Medium: "mid",
  High: "high",
  Unknown: "na",
};

export const SEVERITY_TEXT: Record<string, string> = {
  info: "Info",
  warning: "Warning",
  critical: "Critical",
};
