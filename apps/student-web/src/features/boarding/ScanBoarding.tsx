/**
 * "Scan Boarding QR" — prototype boarding flow (Feature 8).
 *
 * Shows the student's ASSIGNED bus / boarding stop / current trip from the backend,
 * a clearly SIMULATED scanner, and the backend's verdict. All validation and the
 * occupancy numbers come from `POST /boarding/scan`; nothing is decided or counted
 * in the browser, and the student cannot pick a bus, trip, stop or student.
 */
import { useCallback, useState } from "react";

import { ApiError } from "../../api/client";
import { useApi } from "../../api/ApiContext";
import type { BoardingScanOut, MyBoardingOut, OccupancyOut, QrPayload } from "../../api/types";
import { ErrorState, Loading } from "../../components/StateViews";
import { useAsync } from "../../hooks/useAsync";
import { simulatedPayload, type OnScan } from "./scanner";

type Outcome =
  | { kind: "boarded" | "already_boarded"; scan: BoardingScanOut }
  | { kind: "bus_full"; message: string }
  | { kind: "rejected"; code: string; message: string };

interface Props {
  /** Simulation time to stamp the (synthetic) QR with; falls back to the wall clock. */
  simNowIso: string | null;
  /** Called after the backend recorded (or confirmed) a boarding — e.g. refresh the dashboard. */
  onBoarded?: () => void;
}

export function ScanBoarding({ simNowIso, onBoarded }: Props) {
  const api = useApi();
  const loader = useCallback(() => api.myBoarding(), [api]);
  const boarding = useAsync(loader, "my-boarding");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const onScan: OnScan = useCallback(
    (payload: QrPayload) => {
      setBusy(true);
      api
        .scanBoarding({ ...payload, scanner: "simulated" })
        .then((scan) => {
          setOutcome({ kind: scan.status, scan });
          onBoarded?.();
          boarding.reload();
        })
        .catch((e: unknown) => {
          if (e instanceof ApiError && e.code === "bus_full") {
            setOutcome({ kind: "bus_full", message: e.message });
          } else if (e instanceof ApiError) {
            setOutcome({ kind: "rejected", code: e.code, message: e.message });
          } else {
            setOutcome({ kind: "rejected", code: "error", message: String(e) });
          }
        })
        .finally(() => setBusy(false));
    },
    [api, onBoarded, boarding],
  );

  if (boarding.status === "loading") return <Loading label="Loading your boarding details…" />;
  if (boarding.status === "error") {
    return <ErrorState error={boarding.error} onRetry={boarding.reload} />;
  }
  return (
    <div className="boarding">
      <SimulatedScanner
        boarding={boarding.data}
        timestampIso={simNowIso ?? new Date().toISOString()}
        busy={busy}
        onScan={onScan}
      />
      {outcome && <ScanOutcome outcome={outcome} />}
    </div>
  );
}

/** The prototype scanner. A camera scanner would render instead and call the same `onScan`. */
export function SimulatedScanner({
  boarding: b,
  timestampIso,
  busy,
  onScan,
}: {
  boarding: MyBoardingOut;
  timestampIso: string;
  busy: boolean;
  onScan: OnScan;
}) {
  const payload = simulatedPayload(b, timestampIso);
  const status = b.boarded
    ? "Already boarded this trip"
    : b.ready
      ? "Ready to scan"
      : (b.reason ?? "Not ready");
  return (
    <section className="scanner" aria-label="Simulated QR scanner">
      <div className="scanner-frame" aria-hidden="true">
        <span className="scanner-qr">▣</span>
        <span className="scanner-line" />
      </div>
      <p className="scanner-label">Demo scanner — simulates scanning the QR code on your bus</p>
      <dl className="scanner-facts">
        <div>
          <dt>Student</dt>
          <dd>{b.student_id}</dd>
        </div>
        <div>
          <dt>Assigned bus</dt>
          <dd>{b.bus_number ? `BUS ${b.bus_number}` : "—"}</dd>
        </div>
        <div>
          <dt>Boarding stop</dt>
          <dd>{b.boarding_stop?.name ?? "—"}</dd>
        </div>
        <div>
          <dt>Trip</dt>
          <dd>{b.trip_id ?? "No trip running"}</dd>
        </div>
      </dl>
      <p className="scanner-status" role="status" aria-label={`Status: ${status}`}>
        <strong>Status:</strong> {status}
      </p>
      <button
        type="button"
        className="btn btn-primary btn-block"
        disabled={payload === null || busy}
        onClick={() => payload && onScan(payload)}
      >
        {busy ? "Scanning…" : "Simulate Scan"}
      </button>
    </section>
  );
}

export function OccupancySummary({ busNumber, o }: { busNumber: string; o: OccupancyOut }) {
  return (
    <div className="occ-summary" aria-label={`Bus ${busNumber} occupancy`}>
      <strong className="occ-summary-bus">BUS {busNumber}</strong>
      <span>
        {o.occupancy} / {o.capacity} passengers
      </span>
      <span>{o.occupancy_percentage === null ? "—" : `${o.occupancy_percentage}% occupied`}</span>
      <span>
        {o.available_seats} seat{o.available_seats === 1 ? "" : "s"} available
      </span>
    </div>
  );
}

function ScanOutcome({ outcome }: { outcome: Outcome }) {
  switch (outcome.kind) {
    case "boarded":
    case "already_boarded": {
      const boarded = outcome.kind === "boarded";
      return (
        <section
          className={`scan-result ${boarded ? "scan-ok" : "scan-dup"}`}
          aria-label="Scan result"
          role="alert"
        >
          <h3>{boarded ? "Boarding recorded" : "Already boarded"}</h3>
          {!boarded && <p>You have already boarded this trip.</p>}
          <OccupancySummary busNumber={outcome.scan.bus_id} o={outcome.scan} />
        </section>
      );
    }
    case "bus_full":
      return (
        <section className="scan-result scan-bad" aria-label="Scan result" role="alert">
          <h3>Bus full</h3>
          <p>No seats are currently available.</p>
        </section>
      );
    case "rejected":
      return (
        <section className="scan-result scan-bad" aria-label="Scan result" role="alert">
          <h3>Boarding not recorded</h3>
          <p>{outcome.message}</p>
        </section>
      );
  }
}
