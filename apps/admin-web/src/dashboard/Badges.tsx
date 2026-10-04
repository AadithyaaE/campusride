/** Status badges — text + tone, never colour alone. Values are the backend's. */
import { CROWDING_TONE, OPS_LABEL, ROUTE_LABEL, routeTone, TRIP_LABEL } from "../labels";

export function OpsBadge({ status }: { status: string }) {
  return <span className={`badge-ops ops-${status}`}>{OPS_LABEL[status] ?? status}</span>;
}

export function RouteStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="muted">—</span>;
  return (
    <span className={`badge-route route-${routeTone(status)}`}>
      {ROUTE_LABEL[status] ?? status}
    </span>
  );
}

export function CrowdingBadge({ crowding }: { crowding: string }) {
  return <span className={`badge-crowd crowd-${CROWDING_TONE[crowding] ?? "na"}`}>{crowding}</span>;
}

export function TripBadge({ status }: { status: string }) {
  return <span className={`badge-trip trip-${status}`}>{TRIP_LABEL[status] ?? status}</span>;
}

export function GpsBadge({ gps }: { gps: string }) {
  return <span className={`badge-gps gps-${gps.toLowerCase()}`}>{gps}</span>;
}

/** Backend occupancy as "38/50" with a bar sized by the backend percentage. */
export function OccupancyCell({
  occupancy,
  capacity,
  pct,
  crowding,
}: {
  occupancy: number | null;
  capacity: number;
  pct: number | null;
  crowding: string;
}) {
  if (occupancy === null) return <span className="muted">—</span>;
  return (
    <span className="occ">
      <span className="occ-num">
        {occupancy}/{capacity}
      </span>
      <span className="occ-bar" aria-hidden="true">
        <span
          className={`occ-fill crowd-${CROWDING_TONE[crowding] ?? "na"}`}
          style={{ width: `${Math.min(pct ?? 0, 100)}%` }}
        />
      </span>
      <span className="occ-pct">{pct === null ? "—" : `${pct}%`}</span>
    </span>
  );
}
