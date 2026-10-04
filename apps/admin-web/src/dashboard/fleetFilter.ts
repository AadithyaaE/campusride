/** Fleet filters operate on the backend's fleet rows (equality on backend fields only). */
import type { FleetBus } from "../api/client";

export interface FleetFilter {
  route: string;
  bus: string;
  status: string;
}

export const NO_FILTER: FleetFilter = { route: "", bus: "", status: "" };

export const isFiltered = (f: FleetFilter) => Boolean(f.route || f.bus || f.status);

export function applyFleetFilter(buses: FleetBus[], f: FleetFilter): FleetBus[] {
  return buses.filter(
    (b) =>
      (!f.route || b.route_id === f.route) &&
      (!f.bus || b.bus_id === f.bus) &&
      (!f.status || b.operational_status === f.status),
  );
}

/** Buses out on a running trip (backend operational status). */
export const ON_TRIP = new Set(["active", "delayed", "deviated", "breakdown"]);
