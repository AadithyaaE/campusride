/** Display formatting only (campus time). No business values are computed here. */

const TIME = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export const campusTime = (iso: string | null | undefined): string =>
  iso ? TIME.format(new Date(iso)) : "—";

/** Feature 10 route status as the backend reports it (labels only). */
export const ROUTE_STATUS_LABEL: Record<string, string> = {
  NORMAL: "ON ROUTE",
  MINOR_DEVIATION: "MINOR DEVIATION",
  MAJOR_DEVIATION: "MAJOR DEVIATION",
  STALE: "GPS STALE",
  NO_LIVE_DATA: "NO LIVE DATA",
  NO_ACTIVE_TRIP: "NO ACTIVE TRIP",
  NO_ROUTE: "NO ROUTE",
  INVALID_LOCATION: "INVALID LOCATION",
};

export const TRIP_LABEL: Record<string, string> = {
  READY: "READY",
  ACTIVE: "DRIVING",
  COMPLETED: "TRIP COMPLETED",
  NO_TRIP: "NO TRIP TODAY",
  NO_ASSIGNMENT: "NO BUS ASSIGNED",
};
