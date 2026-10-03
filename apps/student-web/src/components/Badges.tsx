import type { Direction } from "../api/types";
import { DIRECTION_LABEL } from "../lib/format";

/** Route code chip in the route's backend-provided colour. */
export function RouteChip({
  id,
  color,
  size = "md",
}: {
  id: string;
  color: string;
  size?: "md" | "lg";
}) {
  return (
    <span className={`route-chip route-chip-${size}`} style={{ background: color }}>
      {id}
    </span>
  );
}

export function DirectionTag({ direction }: { direction: Direction }) {
  return (
    <span className={`dir-tag dir-${direction}`}>
      {direction === "to_campus" ? "→ " : "← "}
      {DIRECTION_LABEL[direction]}
    </span>
  );
}

export function SharedBadge({ count }: { count: number }) {
  return (
    <span className="badge badge-shared" title={`Served by ${count} routes`}>
      Shared · {count} routes
    </span>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: string;
  tone?: "neutral" | "brand";
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}
