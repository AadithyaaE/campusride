/**
 * The details column when nothing is selected (Feature 16.5): fleet status at a glance —
 * counts of the backend's operational status per bus (grouping only, no rules) — and the
 * operator's demo controls.
 */
import type { FleetBus } from "../api/client";
import { OPS_LABEL } from "../labels";

const ORDER = [
  "deviated",
  "breakdown",
  "delayed",
  "active",
  "waiting",
  "completed",
  "idle",
  "out_of_service",
];

export function FleetStatus({
  rows,
  onFilter,
}: {
  rows: FleetBus[];
  onFilter: (status: string) => void;
}) {
  const counts = new Map<string, number>();
  for (const b of rows)
    counts.set(b.operational_status, (counts.get(b.operational_status) ?? 0) + 1);
  const issues =
    (counts.get("deviated") ?? 0) + (counts.get("breakdown") ?? 0) + (counts.get("delayed") ?? 0);
  return (
    <section className="panel fleet-status" aria-label="Fleet status">
      <header className="panel-head">
        <h2>Fleet status</h2>
        <span className={`fleet-verdict ${issues > 0 ? "is-issue" : "is-ok"}`}>
          {rows.length === 0 ? "—" : issues > 0 ? `${issues} need attention` : "All buses on track"}
        </span>
      </header>
      <ul className="status-grid">
        {ORDER.filter((s) => counts.get(s)).map((s) => (
          <li key={s}>
            <button
              type="button"
              className={`status-tile ops-tile-${s}`}
              onClick={() => onFilter(s)}
              aria-label={`${counts.get(s)} ${OPS_LABEL[s] ?? s} — show in fleet table`}
            >
              <strong>{counts.get(s)}</strong>
              <span>{OPS_LABEL[s] ?? s}</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="muted small hint-line">
        Select a bus on the map or in the fleet table for details.
      </p>
    </section>
  );
}
