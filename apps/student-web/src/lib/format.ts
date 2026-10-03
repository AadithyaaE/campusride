import type { Direction } from "../api/types";

export const DIRECTION_LABEL: Record<Direction, string> = {
  to_campus: "To Campus",
  from_campus: "From Campus",
};

export function formatKm(meters: number): string {
  return `${(meters / 1000).toFixed(1)} km`;
}

/** Timetable offset from the route's first stop (NOT an ETA). */
export function formatOffset(seconds: number): string {
  const min = Math.round(seconds / 60);
  return min === 0 ? "start" : `+${min} min`;
}

/** "07:15" from an ISO timestamp with offset, keeping the backend's local time. */
export function localClock(iso: string): string {
  const m = /T(\d{2}:\d{2})/.exec(iso);
  return m?.[1] ?? iso;
}

/** Campus-local hour from an ISO timestamp with offset (e.g. "...T07:15:00+05:30" → 7). */
export function localHour(iso: string): number | null {
  const m = /T(\d{2}):/.exec(iso);
  return m ? Number(m[1]) : null;
}

export function routeSort(a: string, b: string): number {
  return a.localeCompare(b, "en", { numeric: true });
}

/**
 * Default direction for route views, from the backend's (simulation) clock:
 * before noon students travel to campus, after noon they go home. UI default only.
 */
export function suggestedDirection(localHour: number | null): Direction {
  return localHour !== null && localHour >= 12 ? "from_campus" : "to_campus";
}

/** "2.1 km" / "350 m" / "—". */
export function formatDistance(meters: number | null): string {
  if (meters === null) return "—";
  if (meters < 50) return "At stop";
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters / 10) * 10} m`;
}

/** "6 min" / "Now" / "—". */
export function formatEta(minutes: number | null): string {
  if (minutes === null) return "—";
  return minutes <= 0 ? "Now" : `${minutes} min`;
}

/** Campus-local clock time (e.g. "07:42:10") for an ISO timestamp from the backend. */
export function formatCampusTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: CAMPUS_TIME_ZONE,
  });
}

export const CAMPUS_TIME_ZONE = "Asia/Kolkata";

/** Backend `stops_away` → "at the stop" / "next stop" / "3 stops away" (null when passed). */
export function stopsAwayText(n: number | null | undefined): string | null {
  if (n === null || n === undefined) return null;
  return n === 0 ? "at the stop" : n === 1 ? "next stop" : `${n} stops away`;
}
