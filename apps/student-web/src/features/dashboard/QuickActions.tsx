import { useState } from "react";

interface Props {
  busId: string | null;
  onViewStop: () => void;
  onViewAllBuses: () => void;
  onViewRoute: () => void;
}

/** Student quick actions. Deliberately NO "change stop/bus" — assignments are college-managed. */
export function QuickActions({ busId, onViewStop, onViewAllBuses, onViewRoute }: Props) {
  const [qrOpen, setQrOpen] = useState(false);
  return (
    <section aria-label="Quick actions">
      <h3 className="section-title">Quick actions</h3>
      <div className="quick-actions">
        <button type="button" className="qa" onClick={onViewStop}>
          <span aria-hidden="true">📍</span>View boarding stop
        </button>
        <button type="button" className="qa" onClick={onViewAllBuses}>
          <span aria-hidden="true">🚌</span>View all buses
        </button>
        <button type="button" className="qa" onClick={() => setQrOpen(true)}>
          <span aria-hidden="true">▣</span>Scan boarding QR
        </button>
        <button type="button" className="qa" onClick={onViewRoute}>
          <span aria-hidden="true">🗺</span>View route
        </button>
      </div>
      {qrOpen && (
        <div className="modal-backdrop" onClick={() => setQrOpen(false)}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="qr-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="qr-title">Scan boarding QR</h2>
            <div className="qr-placeholder" aria-hidden="true">
              ▣
            </div>
            <p>
              QR boarding arrives in Phase 5. You’ll scan the code inside{" "}
              {busId ? <strong>Bus {busId}</strong> : "your bus"} when you board, and live occupancy
              will come from those scans.
            </p>
            <button
              type="button"
              className="btn btn-primary btn-block"
              onClick={() => setQrOpen(false)}
            >
              Close
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
