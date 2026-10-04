/**
 * ─────────────────────────────────────────────────────────────────────────
 *  Dashboard display helpers (labels + small type guards)
 * ─────────────────────────────────────────────────────────────────────────
 *
 * AUTHORITATIVE (backend — never recomputed here):
 *   positions, status, which buses serve the student's stop, current / previous /
 *   next stop, distance, proximity, AND the ETA (`eta_minutes`,
 *   `estimated_arrival_time`, traffic, confidence) — `GET /students/me/arrivals`,
 *   and the multi-bus comparison (crowding, FASTEST / LEAST_CROWDED / ASSIGNED /
 *   BEST_ALTERNATIVE) — `GET /students/me/bus-options`, and "Will I make my bus?"
 *   (YES / RISK / MISSED) — `GET /students/me/commute-decision`, missed-bus
 *   recovery — `GET /students/me/recovery-options`, and in-app alerts
 *   (Feature 11) — `GET /alerts`.
 *
 * There is deliberately NO ETA formula, NO commute decision and NO alert
 * generation in the browser (the former interim alert rules were removed in
 * Feature 11).
 */
import type {
  ArrivalOut,
  BusStatus,
  MyArrivalsOut,
  StopBusOut,
  StopProximity,
} from "../../api/types";

export const STATUS_LABEL: Record<BusStatus, string> = {
  scheduled: "Scheduled",
  at_depot: "At first stop",
  en_route: "On route",
  dwelling: "At stop",
  deviated: "Off route",
  breakdown: "Breakdown",
  completed: "Completed",
};

export const PROXIMITY_LABEL: Record<StopProximity, string> = {
  far_from_stop: "On the way",
  approaching_stop: "Approaching your stop",
  at_stop: "At your stop",
  passed_stop: "Passed your stop",
};

export const hasEta = (b: ArrivalOut | StopBusOut | null | undefined): b is ArrivalOut =>
  !!b && "eta" in b && !!(b as ArrivalOut).eta;

/** Backend ETA in whole minutes (null when the backend has none). Display only. */
export const backendEtaMin = (b: ArrivalOut | StopBusOut | null | undefined): number | null =>
  hasEta(b) ? b.eta.eta_minutes : null;

/** The other buses at the student's stop, in the backend's ETA order. */
export const otherArrivals = (a: MyArrivalsOut | null): ArrivalOut[] =>
  a?.status === "assigned" ? a.arrivals.filter((x) => !x.is_assigned_bus) : [];
