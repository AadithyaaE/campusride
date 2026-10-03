/**
 * BUS OPTIONS — the backend's multi-bus comparison for the student's ASSIGNED
 * boarding stop (`GET /students/me/bus-options`, Feature 6).
 *
 * Display only: ETA, crowding, indicators (FASTEST / LEAST_CROWDED / ASSIGNED /
 * BEST_ALTERNATIVE) and the trade-off text all come from the backend. The browser
 * computes no score and does not re-rank — options stay in the backend's arrival
 * order. Selecting a card only highlights that bus on the map; the college
 * assignment never changes here.
 */
import type { BusIndicator, BusOptionOut, BusOptionsOut } from "../../api/types";
import { EmptyState } from "../../components/StateViews";
import type { SimReference } from "../../lib/countdown";
import { stopsAwayText } from "../../lib/format";
import { EtaCountdown, SimTag } from "./LiveCards";

const INDICATOR_LABEL: Record<BusIndicator, string> = {
  ASSIGNED: "Assigned",
  FASTEST: "Fastest",
  LEAST_CROWDED: "Least crowded",
  BEST_ALTERNATIVE: "Best alternative",
};

const EXCLUDED_LABEL = { passed_stop: "passed your stop", trip_completed: "trip finished" };

interface Props {
  options: BusOptionsOut;
  simRef: SimReference | null;
  selectedBusId: string | null;
  onSelectBus: (busId: string | null) => void;
}

export function BusOptions({ options, simRef, selectedBusId, onSelectBus }: Props) {
  const stop = options.boarding_stop?.name ?? "your stop";
  const others = options.options.filter((o) => !o.is_assigned_bus).length;
  return (
    <section id="bus-options" className="live-card bus-options" aria-label="Bus options">
      <header className="live-card-head">
        <p className="eyebrow">Bus options · {stop}</p>
        <SimTag />
      </header>
      {options.assigned_bus_note && <p className="opt-note">{options.assigned_bus_note}</p>}
      {options.options.length === 0 ? (
        <EmptyState title="No bus is due at your stop right now" />
      ) : (
        <ul className="opt-list" aria-label="Buses serving my stop">
          {options.options.map((o) => (
            <li key={o.bus_id}>
              <OptionCard
                option={o}
                simRef={simRef}
                selected={o.bus_id === selectedBusId}
                onToggle={() => onSelectBus(o.bus_id === selectedBusId ? null : o.bus_id)}
              />
            </li>
          ))}
        </ul>
      )}
      {options.options.length > 0 && others === 0 && (
        <p className="opt-note">No other bus serves your stop in your direction right now.</p>
      )}
      {options.excluded.length > 0 && (
        <p className="footnote">
          Not shown:{" "}
          {options.excluded.map((x) => `${x.bus_number} (${EXCLUDED_LABEL[x.reason]})`).join(", ")}
        </p>
      )}
      <p className="footnote">
        Compared by the backend. Best alternative = the strongest option besides the fastest,
        balancing arrival time, crowding, delay and ETA confidence. Your assigned bus doesn’t
        change.
      </p>
    </section>
  );
}

function OptionCard({
  option: o,
  simRef,
  selected,
  onToggle,
}: {
  option: BusOptionOut;
  simRef: SimReference | null;
  selected: boolean;
  onToggle: () => void;
}) {
  const away =
    o.match?.proximity === "at_stop" ? "At your stop" : stopsAwayText(o.match?.stops_away);
  const details = [
    `${o.eta.traffic} traffic`,
    away,
    o.delay_minutes >= 1 ? `+${o.delay_minutes} min delay` : null,
    o.stale ? "Live data delayed" : null,
  ].filter(Boolean);
  return (
    <button
      type="button"
      className={`opt-card crowd-${o.crowding.toLowerCase()}${o.is_assigned_bus ? " is-mine" : ""}${
        selected ? " is-selected" : ""
      }`}
      aria-pressed={selected}
      aria-label={`Bus ${o.bus_number}`}
      title={selected ? "Shown on the map — tap again to clear" : "Show this bus on the map"}
      onClick={onToggle}
    >
      <span className="opt-top">
        <span className="opt-bus">Bus {o.bus_number}</span>
        <EtaCountdown eta={o.eta} simRef={simRef} showMeta={false} />
      </span>
      {o.indicators.length > 0 && (
        <span className="opt-badges">
          {o.indicators.map((i) => (
            <span key={i} className={`opt-badge opt-badge-${i.toLowerCase().replace("_", "-")}`}>
              {INDICATOR_LABEL[i]}
            </span>
          ))}
        </span>
      )}
      <span className="opt-crowd">
        <span className="opt-occ">
          {o.occupancy} / {o.capacity}
        </span>
        <span className="opt-crowd-label">
          {o.crowding === "Unknown" ? "Crowding unknown" : `${o.crowding} crowding`}
        </span>
        <span className="occ-track" aria-hidden="true">
          <span
            className="occ-fill"
            style={{ width: `${Math.min(100, o.occupancy_percentage ?? 0)}%` }}
          />
        </span>
      </span>
      <span className="opt-meta">{details.join(" · ")}</span>
      {o.trade_off && <span className="opt-trade">{o.trade_off}</span>}
    </button>
  );
}
