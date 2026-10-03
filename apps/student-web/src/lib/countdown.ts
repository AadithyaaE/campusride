/**
 * Display countdown for a BACKEND ETA — never a second ETA formula.
 *
 * The backend returns `computed_at` (simulation time of the prediction) and
 * `estimated_arrival_time`. Between polls the browser only advances the
 * simulated "now" from that reference point:
 *
 *   simNow = computed_at + (wall time since the poll) × simulation speed   (frozen when paused)
 *
 * and formats `estimated_arrival_time − simNow` as whole minutes.
 */
import { useEffect, useState } from "react";

import type { EtaPredictionOut } from "../api/types";

export interface SimReference {
  /** Wall-clock ms when the poll that produced the ETA completed. */
  fetchedAtMs: number;
  speed: number;
  paused: boolean;
}

export function simNowMs(computedAtIso: string, ref: SimReference, wallNowMs: number): number {
  const base = Date.parse(computedAtIso);
  if (ref.paused) return base;
  return base + Math.max(0, wallNowMs - ref.fetchedAtMs) * ref.speed;
}

/** Remaining whole seconds to the backend's estimated arrival (null when no ETA). */
export function remainingSeconds(
  eta: EtaPredictionOut,
  ref: SimReference | null,
  wallNowMs: number,
): number | null {
  if (eta.status !== "predicted" || !eta.estimated_arrival_time) return null;
  const now = ref ? simNowMs(eta.computed_at, ref, wallNowMs) : Date.parse(eta.computed_at);
  return Math.round((Date.parse(eta.estimated_arrival_time) - now) / 1000);
}

/** "6 min" · "<1 min" · "Arriving" · "Arrived" · "Passed" · "Completed" — never decimals. */
export function countdownLabel(
  eta: EtaPredictionOut,
  ref: SimReference | null,
  wallNowMs: number,
): string {
  switch (eta.status) {
    case "at_stop":
      return "Arrived";
    case "passed":
      return "Passed";
    case "completed":
      return "Completed";
  }
  const left = remainingSeconds(eta, ref, wallNowMs);
  if (left === null) return "—";
  if (left <= 0) return "Arriving";
  if (left < 60) return "<1 min";
  return `${Math.ceil(left / 60)} min`;
}

/** Re-render every `intervalMs` so countdowns tick down between polls. */
export function useWallClock(intervalMs = 1_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
