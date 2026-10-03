/** Display labels for backend route statuses (Feature 10). Labels only — no logic. */
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
