import type { SimStatusOut } from "../../api/types";
import type { LiveFleet } from "../../data/liveFleet";
import { FALLBACK_POLL_MS } from "../../data/liveFleet";
import { formatCampusTime } from "../../lib/format";

/**
 * DEMO MODE — drives the BACKEND synthetic simulator (`/api/v1/sim/*`).
 * Never touches the student's assignment. Hidden when the backend says the
 * caller may not control the simulation (outside development).
 */
const FEED_TEXT: Record<LiveFleet["realtime"], string> = {
  live: "Live · real-time updates",
  connecting: "Connecting to live updates…",
  offline: `Live updates reconnecting · checking every ${FALLBACK_POLL_MS / 1000} s`,
};

export function DemoControls({
  sim,
  control,
  realtime = "live",
}: {
  sim: SimStatusOut | null;
  control: LiveFleet["control"];
  realtime?: LiveFleet["realtime"];
}) {
  const feed = (
    <p className={`feed-status feed-${realtime}`} role="status" aria-label="Live updates">
      {FEED_TEXT[realtime]}
    </p>
  );
  if (!sim || !sim.enabled) {
    return (
      <section className="demo-controls" aria-label="Demo mode">
        <h3 className="section-title">Simulated live tracking</h3>
        <p className="footnote">The backend simulator is not enabled.</p>
        {feed}
      </section>
    );
  }
  const can = sim.controls_allowed;
  return (
    <section className="demo-controls" aria-label="Demo mode">
      <header className="section-head">
        <h3 className="section-title">Demo mode · Simulated live tracking</h3>
        <span className={`status-chip ${sim.paused ? "status-muted" : "status-good"}`}>
          {sim.paused ? "Paused" : "Running"}
        </span>
      </header>
      <p className="sim-clock">
        Sim time <strong>{sim.local_time ? formatCampusTime(sim.local_time) : "—"}</strong> ·{" "}
        {sim.speed}× · {sim.buses} buses
      </p>
      {can ? (
        <>
          <div className="btn-row">
            {sim.paused ? (
              <button type="button" className="btn btn-primary btn-sm" onClick={control.start}>
                Start simulation
              </button>
            ) : (
              <button type="button" className="btn btn-secondary btn-sm" onClick={control.pause}>
                Pause simulation
              </button>
            )}
            <button type="button" className="btn btn-secondary btn-sm" onClick={control.reset}>
              Reset simulation
            </button>
          </div>
          <div className="segmented segmented-sm" role="radiogroup" aria-label="Simulation speed">
            {sim.allowed_speeds.map((s) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={sim.speed === s}
                className={sim.speed === s ? "is-active" : ""}
                onClick={() => void control.setSpeed(s)}
              >
                {s}×
              </button>
            ))}
          </div>
        </>
      ) : (
        <p className="footnote">Simulation controls are available to administrators only.</p>
      )}
      <p className="footnote">
        Bus positions, status, occupancy, delays and ETAs come from the backend (synthetic
        simulator, no real GPS). The backend pushes every change in real time (WebSocket); if the
        connection drops this page re-checks every {FALLBACK_POLL_MS / 1000} s. Countdowns tick
        between updates. “Will I make my bus?” and alerts are interim rules.
      </p>
      {feed}
    </section>
  );
}
