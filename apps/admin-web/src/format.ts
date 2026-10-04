/** Presentation formatting only (campus time zone, units). No transport logic. */
const TZ = "Asia/Kolkata";

export const timeFmt = new Intl.DateTimeFormat("en-IN", {
  timeZone: TZ,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export const hmFmt = new Intl.DateTimeFormat("en-IN", {
  timeZone: TZ,
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export const dateFmt = new Intl.DateTimeFormat("en-IN", {
  timeZone: TZ,
  weekday: "short",
  day: "2-digit",
  month: "short",
});

export const hm = (iso: string | null | undefined) => (iso ? hmFmt.format(new Date(iso)) : "—");
export const hms = (iso: string | null | undefined) => (iso ? timeFmt.format(new Date(iso)) : "—");

/** "BUS 07" style short number from a backend bus id ("B07" → "07"). */
export const busNo = (id: string) => id.replace(/^B/, "");

export const dash = (v: number | string | null | undefined, unit = "") =>
  v === null || v === undefined ? "—" : `${v}${unit}`;

/** Backend delay minutes as "+8 min" / "−2 min" / "on time". */
export function delayText(min: number | null | undefined): string {
  if (min === null || min === undefined) return "—";
  if (min === 0) return "on time";
  return min > 0 ? `+${min} min` : `−${-min} min`;
}

export function etaText(min: number | null | undefined, status?: string | null): string {
  if (status === "at_stop") return "At stop";
  if (min === null || min === undefined) return "—";
  return min === 0 ? "<1 min" : `${min} min`;
}

export function ageText(s: number | null | undefined): string {
  if (s === null || s === undefined) return "—";
  if (s < 60) return `${s}s ago`;
  return `${Math.floor(s / 60)}m ${s % 60}s ago`;
}
