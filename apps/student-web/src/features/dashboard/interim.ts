/**
 * ─────────────────────────────────────────────────────────────────────────
 *  INTERIM dashboard rules                                  — replaced in Phases 4/6
 * ─────────────────────────────────────────────────────────────────────────
 *
 * AUTHORITATIVE (backend — never recomputed here):
 *   positions, status, which buses serve the student's stop, current / previous /
 *   next stop, distance, proximity, AND the ETA (`eta_minutes`,
 *   `estimated_arrival_time`, traffic, confidence) — `GET /students/me/arrivals`,
 *   and the multi-bus comparison (crowding, FASTEST / LEAST_CROWDED / ASSIGNED /
 *   BEST_ALTERNATIVE) — `GET /students/me/bus-options`, and "Will I make my bus?"
 *   (YES / RISK / MISSED) — `GET /students/me/commute-decision`, and missed-bus
 *   recovery — `GET /students/me/recovery-options`.
 *
 * INTERIM (this file):
 *   • alerts = simple rules over backend data → Phase 6 alerts
 *
 * There is deliberately NO ETA formula and NO commute decision in the browser.
 */
import type {
  ArrivalOut,
  BusOut,
  BusStatus,
  CommuteDecisionOut,
  MyArrivalsOut,
  RecoveryOut,
  StopBusOut,
  StopProximity,
} from "../../api/types";

const CAPACITY_WARN_PCT = 85;

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

export interface DashboardAlert {
  id: string;
  kind: "approaching" | "delay" | "capacity" | "deviation" | "alternative";
  severity: "info" | "warning";
  title: string;
  body: string;
}

export const hasEta = (b: ArrivalOut | StopBusOut | null | undefined): b is ArrivalOut =>
  !!b && "eta" in b && !!(b as ArrivalOut).eta;

/** Backend ETA in whole minutes (null when the backend has none). Display only. */
export const backendEtaMin = (b: ArrivalOut | StopBusOut | null | undefined): number | null =>
  hasEta(b) ? b.eta.eta_minutes : null;

/** The other buses at the student's stop, in the backend's ETA order. */
export const otherArrivals = (a: MyArrivalsOut | null): ArrivalOut[] =>
  a?.status === "assigned" ? a.arrivals.filter((x) => !x.is_assigned_bus) : [];

export function dashboardAlerts(
  a: MyArrivalsOut | null,
  commute: CommuteDecisionOut | null,
  recovery: RecoveryOut | null,
  allBuses: BusOut[],
): DashboardAlert[] {
  const out: DashboardAlert[] = [];
  if (!a || a.status !== "assigned" || !a.boarding_stop) return out;
  const stopName = a.boarding_stop.name;
  const mine = a.my_bus;
  const p = mine?.match?.proximity;
  if (mine && a.my_bus_serving_stop && (p === "approaching_stop" || p === "at_stop")) {
    const eta = backendEtaMin(mine);
    out.push({
      id: `approaching-${mine.bus_id}`,
      kind: "approaching",
      severity: "info",
      title:
        p === "at_stop"
          ? `Bus ${mine.bus_id} is at your stop`
          : `Bus ${mine.bus_id} is approaching`,
      body:
        p === "at_stop"
          ? `At ${stopName} now.`
          : eta !== null && eta > 0
            ? `About ${eta} min from ${stopName}.`
            : `Less than a minute from ${stopName}.`,
    });
  }
  if (mine && mine.schedule_status === "delayed") {
    out.push({
      id: `delay-${mine.bus_id}`,
      kind: "delay",
      severity: "warning",
      title: `Bus ${mine.bus_id} is running late`,
      body: `About ${Math.round(mine.delay_s / 60)} min behind the timetable.`,
    });
  }
  for (const b of [...(mine ? [mine] : []), ...otherArrivals(a)]) {
    if (
      b.match &&
      b.match.proximity !== "passed_stop" &&
      (b.occupancy_percentage ?? 0) >= CAPACITY_WARN_PCT
    ) {
      out.push({
        id: `capacity-${b.bus_id}`,
        kind: "capacity",
        severity: "warning",
        title: `Bus ${b.bus_id} is ${b.occupancy_percentage}% full`, // backend percentage
        body: `${b.occupancy}/${b.capacity} seats taken on ${b.route_direction_id}.`,
      });
    }
  }
  for (const b of allBuses) {
    if (b.live?.route_status === "MAJOR_DEVIATION") {
      out.push({
        id: `deviation-${b.id}`,
        kind: "deviation",
        severity: "warning",
        title: `Bus ${b.id} is off its planned route`,
        body:
          b.live.deviation_distance_m === null
            ? `${b.live.route_direction_id ?? b.route_id}.`
            : `Currently ${Math.round(b.live.deviation_distance_m)} m from its planned route.`,
      });
    }
  }
  // The suggestion comes from the BACKEND recovery service (Feature 9) — never a reassignment.
  const best = recovery?.status === "recovery_available" ? recovery.recommended : null;
  if ((commute?.decision === "RISK" || commute?.decision === "MISSED") && best) {
    out.push({
      id: `alternative-${best.bus_id}`,
      kind: "alternative",
      severity: "info",
      title: `Alternative: Bus ${best.bus_number} (${best.route_direction_id})`,
      body: `${best.reason} Your assigned bus stays ${a.assigned_bus_id}.`,
    });
  }
  return out;
}
