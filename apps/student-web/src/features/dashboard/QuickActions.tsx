import { useState } from "react";

import { ScanBoarding } from "../boarding/ScanBoarding";
import { Icon } from "../../components/Icon";

interface Props {
  busId: string | null;
  /** Simulation time for the synthetic QR timestamp. */
  simNowIso: string | null;
  /** Refresh live data after the backend records a boarding. */
  onBoarded: () => void;
  onViewStop: () => void;
  onViewAllBuses: () => void;
  onViewRoute: () => void;
}

/** Student quick actions. Deliberately NO "change stop/bus" — assignments are college-managed. */
export function QuickActions({
  busId,
  simNowIso,
  onBoarded,
  onViewStop,
  onViewAllBuses,
  onViewRoute,
}: Props) {
  const [qrOpen, setQrOpen] = useState(false);
  return (
    <section aria-label="Quick actions">
      <h3 className="section-title">Quick actions</h3>
      <div className="quick-actions">
        <button type="button" className="qa" onClick={onViewStop}>
          <Icon name="pin" size={20} />
          View boarding stop
        </button>
        <button type="button" className="qa" onClick={onViewAllBuses}>
          <Icon name="bus" size={20} />
          View all buses
        </button>
        <button type="button" className="qa" onClick={() => setQrOpen(true)}>
          <Icon name="ticket" size={20} />
          Scan Boarding QR
        </button>
        <button type="button" className="qa" onClick={onViewRoute}>
          <Icon name="route" size={20} />
          View route
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
            <h2 id="qr-title">Scan Boarding QR</h2>
            {busId ? (
              <ScanBoarding simNowIso={simNowIso} onBoarded={onBoarded} />
            ) : (
              <p>Your bus assignment is not available yet.</p>
            )}
            <button type="button" className="btn btn-block" onClick={() => setQrOpen(false)}>
              Close
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
