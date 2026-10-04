/** "just now" / "4 min ago" relative to SIMULATION time (display only). */
export function ago(timestamp: string, nowIso: string | null): string {
  if (!nowIso) return "";
  const min = Math.floor((Date.parse(nowIso) - Date.parse(timestamp)) / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  return `${Math.floor(min / 60)} h ago`;
}
