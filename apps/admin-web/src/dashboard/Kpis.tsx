/** KPI cards (Feature 13) — `GET /admin/overview`, displayed exactly as the backend counted. */
import type { AdminOverview } from "../api/client";

function Kpi({
  label,
  value,
  sub,
  title,
}: {
  label: string;
  value: number | null;
  sub: string;
  title?: string;
}) {
  return (
    <div className="kpi" role="group" aria-label={label} title={title}>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value === null ? "—" : value.toLocaleString("en-IN")}</span>
      <span className="kpi-sub">{sub}</span>
    </div>
  );
}

export function KpiStrip({
  overview,
  error,
}: {
  overview: AdminOverview | null;
  error: string | null;
}) {
  const o = overview;
  return (
    <section className="kpis" aria-label="Key figures">
      <Kpi
        label="Total buses"
        value={o?.total_buses ?? null}
        sub={o ? `${o.buses_in_service} in service · ${o.buses_on_trip} on trip` : "…"}
      />
      <Kpi
        label="Active trips"
        value={o?.active_trips ?? null}
        sub={
          o
            ? `${o.trips_today.completed} done · ${o.trips_today.scheduled} scheduled of ${o.trips_today.total}`
            : "…"
        }
      />
      <Kpi
        label="Students"
        value={o?.students ?? null}
        sub={o ? `${o.assigned_students} assigned to a bus` : "…"}
      />
      <Kpi
        label="Passengers today"
        value={o?.passengers_today ?? null}
        sub={o ? `${o.qr_boardings_today} QR boardings` : "…"}
        title={o?.passengers_method}
      />
      <div className="kpi-flags" aria-label="Exceptions">
        <span className={`flag${o && o.delayed_buses > 0 ? " flag-warn" : ""}`}>
          <strong>{o?.delayed_buses ?? "—"}</strong> delayed
        </span>
        <span
          className={`flag${o && o.major_deviations > 0 ? " flag-crit" : o && o.deviated_buses > 0 ? " flag-warn" : ""}`}
        >
          <strong>{o?.deviated_buses ?? "—"}</strong> off route
        </span>
        <span className={`flag${o && o.alerts.critical > 0 ? " flag-crit" : ""}`}>
          <strong>{o?.alerts.unread ?? "—"}</strong> unread alerts
        </span>
      </div>
      {error && (
        <p className="error small kpi-error" role="alert">
          Overview: {error}
        </p>
      )}
    </section>
  );
}
