import { EmptyState } from "../../components/StateViews";
import type { DashboardAlert } from "./interim";
import { SimTag } from "./LiveCards";

const ICON: Record<DashboardAlert["kind"], string> = {
  approaching: "🚌",
  delay: "⏱",
  capacity: "👥",
  deviation: "↪",
  alternative: "⇄",
};

export function AlertsList({ alerts }: { alerts: DashboardAlert[] }) {
  return (
    <section id="alerts" aria-label="Alerts">
      <header className="section-head">
        <h3 className="section-title">Alerts</h3>
        <SimTag />
      </header>
      {alerts.length === 0 ? (
        <EmptyState title="No alerts right now" />
      ) : (
        <ul className="alerts" aria-label="Alert list">
          {alerts.map((a) => (
            <li key={a.id} className={`alert alert-${a.severity}`}>
              <span className="alert-icon" aria-hidden="true">
                {ICON[a.kind]}
              </span>
              <span className="row-main">
                <strong>{a.title}</strong>
                <span className="row-sub">{a.body}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="footnote">
        Demonstration alerts derived from simulated bus data — not production alerts.
      </p>
    </section>
  );
}
