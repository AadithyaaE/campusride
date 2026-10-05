/**
 * Demo controls for the operator recording a walkthrough (Feature 16.5). Collapsed by default
 * and admin-only. Every button calls the EXISTING backend simulator API (`/sim/*`), so the
 * Student, Driver and Admin screens react exactly as they would to real events — nothing is
 * faked in the UI. Trip start and boarding stay in the Driver and Student apps.
 */
import { useEffect, useState } from "react";

import type { AdminApi, FleetBus, RouteDeviationDemoMode, SimStatusOut } from "../api/client";

export function DemoControls({ api, rows }: { api: AdminApi; rows: FleetBus[] }) {
  const [open, setOpen] = useState(false);
  const [sim, setSim] = useState<SimStatusOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busId, setBusId] = useState("B07");

  useEffect(() => {
    if (!open) return;
    api
      .simStatus()
      .then(setSim, (e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [api, open]);

  const run = (call: () => Promise<SimStatusOut>) => {
    setBusy(true);
    setError(null);
    call()
      .then(setSim, (e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false));
  };
  const deviate = (mode: RouteDeviationDemoMode) => run(() => api.setRouteDeviation(mode, busId));
  const simBuses = rows.filter((b) => b.source === "sim");

  return (
    <section className="panel demo-controls" aria-label="Demo controls">
      <button
        type="button"
        className="demo-toggle"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span>Demo controls</span>
        <span className="muted small">{open ? "Hide" : "For recording a walkthrough"}</span>
      </button>
      {open && (
        <div className="demo-body">
          {error && (
            <p className="error small" role="alert">
              {error}
            </p>
          )}
          {sim && !sim.controls_allowed && (
            <p className="muted small">Simulator controls are not available for this account.</p>
          )}
          {sim?.controls_allowed && (
            <>
              <div className="demo-row">
                <span className="demo-label">Simulation</span>
                <span className={`demo-state ${sim.paused ? "is-paused" : "is-running"}`}>
                  {sim.paused ? "Paused" : "Running"}
                </span>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={busy}
                  onClick={() => run(() => (sim.paused ? api.simStart() : api.simPause()))}
                >
                  {sim.paused ? "Resume" : "Pause"}
                </button>
              </div>
              <div className="demo-row" role="radiogroup" aria-label="Simulation speed">
                <span className="demo-label">Speed</span>
                {sim.allowed_speeds.map((s) => (
                  <button
                    key={s}
                    type="button"
                    role="radio"
                    aria-checked={sim.speed === s}
                    className={`btn btn-sm${sim.speed === s ? " btn-primary" : ""}`}
                    disabled={busy}
                    onClick={() => run(() => api.simSpeed(s))}
                  >
                    {s}×
                  </button>
                ))}
              </div>
              <div className="demo-row">
                <label className="demo-label" htmlFor="demo-bus">
                  Route deviation
                </label>
                <select id="demo-bus" value={busId} onChange={(e) => setBusId(e.target.value)}>
                  {simBuses.map((b) => (
                    <option key={b.bus_id} value={b.bus_id}>
                      Bus {b.bus_id}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={busy}
                  onClick={() => deviate("major")}
                >
                  Send off route
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={busy}
                  onClick={() => deviate("normal")}
                >
                  Back to normal
                </button>
              </div>
              <div className="demo-row">
                <span className="demo-label">Demo day</span>
                <button
                  type="button"
                  className="btn btn-sm btn-danger-ghost"
                  disabled={busy}
                  onClick={() => run(() => api.simReset())}
                >
                  Reset to start of day
                </button>
              </div>
            </>
          )}
          <ol className="demo-steps">
            <li>
              Start Bus B07&apos;s trip in the <strong>Driver app</strong> (driver07).
            </li>
            <li>
              Board from the <strong>Student app</strong>: Scan Boarding QR.
            </li>
            <li>Send B07 off route here, then bring it back to normal.</li>
            <li>Reset to the start of the day when you&apos;re done.</li>
          </ol>
        </div>
      )}
    </section>
  );
}
