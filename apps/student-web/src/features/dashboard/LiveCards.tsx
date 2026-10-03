import type {
  ArrivalOut,
  AssignmentOut,
  BusStatus,
  EtaPredictionOut,
  StopBusOut,
  StopProximity,
} from "../../api/types";
import { DirectionTag, RouteChip } from "../../components/Badges";
import { countdownLabel, useWallClock, type SimReference } from "../../lib/countdown";
import { formatCampusTime, formatDistance, formatEta, stopsAwayText } from "../../lib/format";
import { hasEta, PROXIMITY_LABEL, STATUS_LABEL, type Decision } from "./interim";

export function SimTag({ label = "Simulated" }: { label?: string }) {
  return (
    <span className="sim-tag" title="Synthetic data from the backend simulator — not real GPS">
      {label}
    </span>
  );
}

export function StatusChip({ status }: { status: BusStatus }) {
  const tone =
    status === "deviated" || status === "breakdown"
      ? "bad"
      : status === "dwelling"
        ? "good"
        : status === "completed" || status === "scheduled"
          ? "muted"
          : "info";
  return <span className={`status-chip status-${tone}`}>{STATUS_LABEL[status]}</span>;
}

export function ProximityChip({ proximity }: { proximity: StopProximity }) {
  const tone =
    proximity === "at_stop" || proximity === "approaching_stop"
      ? "good"
      : proximity === "passed_stop"
        ? "bad"
        : "info";
  return <span className={`status-chip status-${tone}`}>{PROXIMITY_LABEL[proximity]}</span>;
}

export function ScheduleChip({ bus }: { bus: { schedule_status: string; delay_s: number } }) {
  if (bus.schedule_status !== "delayed") return null;
  return (
    <span className="status-chip status-bad">Delayed +{Math.round(bus.delay_s / 60)} min</span>
  );
}

export function OccupancyBar({ occupancy, capacity }: { occupancy: number; capacity: number }) {
  const pct = capacity > 0 ? Math.round((100 * occupancy) / capacity) : 0;
  const tone = pct >= 80 ? "high" : pct >= 60 ? "mid" : "low"; // backend crowding bands (F6)
  return (
    <span className="occ" aria-label={`Occupancy ${occupancy} of ${capacity}`}>
      <span className="occ-text">
        {occupancy}/{capacity}
      </span>
      <span className="occ-track" aria-hidden="true">
        <span className={`occ-fill occ-${tone}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </span>
    </span>
  );
}

const CONFIDENCE_LABEL = { high: "High", medium: "Medium", low: "Low" } as const;

/**
 * BACKEND ETA as a ticking countdown (whole minutes only). The value comes from
 * the backend's `estimated_arrival_time`; the browser only advances the clock.
 */
export function EtaCountdown({
  eta,
  simRef,
  size = "md",
  showMeta = true,
}: {
  eta: EtaPredictionOut;
  simRef: SimReference | null;
  size?: "md" | "lg";
  /** Traffic + confidence chips (hidden where the caller shows traffic itself). */
  showMeta?: boolean;
}) {
  const wallNow = useWallClock();
  const label = countdownLabel(eta, simRef, wallNow);
  return (
    <span className={`eta eta-${size}`} aria-label={`ETA ${label}`}>
      <span className="eta-value">{label}</span>
      {showMeta && eta.status === "predicted" && (
        <span className="eta-meta">
          <span className={`eta-chip eta-traffic-${eta.traffic.toLowerCase()}`}>
            {eta.traffic} traffic
          </span>
          <span className={`eta-chip eta-conf-${eta.confidence}`}>
            {CONFIDENCE_LABEL[eta.confidence]} confidence
          </span>
        </span>
      )}
    </span>
  );
}

/**
 * The college-assigned bus. Position, stops, proximity (Feature 4) and ETA
 * (Feature 5) all come from the backend (`GET /students/me/arrivals`).
 */
export function MyBusLiveCard({
  assignment,
  bus,
  servingStop,
  paused,
  simRef,
}: {
  assignment: AssignmentOut;
  bus: ArrivalOut | StopBusOut | null;
  servingStop: boolean;
  paused: boolean;
  simRef: SimReference | null;
}) {
  const m = servingStop ? bus?.match : null;
  return (
    <section
      className="live-card mybus-live"
      style={{ ["--route-color" as string]: assignment.route.color }}
      aria-label="My bus live"
    >
      <header className="live-card-head">
        <p className="eyebrow">My bus</p>
        <SimTag label={paused ? "Simulated · paused" : "Simulated"} />
      </header>
      <div className="mybus-live-title">
        <span className="bus-number">BUS {assignment.bus.id}</span>
        {bus && <StatusChip status={bus.status} />}
        {bus && <ScheduleChip bus={bus} />}
      </div>
      <p className="mybus-live-route">
        <RouteChip id={assignment.route.route_direction_id} color={assignment.route.color} />
        <span>{assignment.route.name}</span>
        <DirectionTag direction={assignment.route.direction} />
      </p>
      {!bus ? (
        <p className="footnote">
          No live data for bus {assignment.bus.id} yet — start the simulation below.
        </p>
      ) : (
        <>
          {servingStop && hasEta(bus) ? (
            <EtaCountdown eta={bus.eta} simRef={simRef} size="lg" />
          ) : null}
          {m ? (
            <p className="approach">
              <ProximityChip proximity={m.proximity} />
              {stopsAwayText(m.stops_away) && (
                <span className="muted"> · {stopsAwayText(m.stops_away)}</span>
              )}
            </p>
          ) : (
            <p className="approach muted">
              Currently running {bus.direction_label} — not serving your stop right now.
            </p>
          )}
          <dl className="metrics">
            <div>
              <dt>Distance to my stop</dt>
              <dd>
                {!m
                  ? "—"
                  : m.proximity === "passed_stop"
                    ? "Passed"
                    : formatDistance(m.distance_to_stop_m)}
              </dd>
            </div>
            <div>
              <dt>Arrival (sim time)</dt>
              <dd>
                {hasEta(bus) && bus.eta.estimated_arrival_time
                  ? formatCampusTime(bus.eta.estimated_arrival_time).slice(0, 5)
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>Current stop</dt>
              <dd className="metric-text">{bus.position.current_stop.name}</dd>
            </div>
            <div>
              <dt>Next stop</dt>
              <dd className="metric-text">{bus.position.next_stop?.name ?? "—"}</dd>
            </div>
            <div className="metric-wide">
              <dt>Occupancy</dt>
              <dd>
                <OccupancyBar occupancy={bus.occupancy} capacity={bus.capacity} />
              </dd>
            </div>
          </dl>
          <p className="footnote">
            Boarding stop <strong>{assignment.boarding_stop.name}</strong>
            {bus.position.previous_stop && (
              <> · previous stop {bus.position.previous_stop.name}</>
            )}{" "}
            · {assignment.bus.reg_no} · Last updated{" "}
            <time dateTime={bus.last_updated}>{formatCampusTime(bus.last_updated)}</time> (sim time)
          </p>
        </>
      )}
    </section>
  );
}

export function DecisionCard({ decision }: { decision: Decision }) {
  const yes = decision.verdict === "YES";
  return (
    <section
      className={`live-card decision ${yes ? "decision-yes" : "decision-risk"}`}
      aria-label="Will I make my bus?"
    >
      <header className="live-card-head">
        <p className="eyebrow">Will I make my bus?</p>
        <SimTag label="Estimate" />
      </header>
      <p className="decision-headline" role="status">
        <span className="decision-icon" aria-hidden="true">
          {yes ? "✓" : "!"}
        </span>
        {decision.headline}
      </p>
      <p className="decision-detail">{decision.detail}</p>
      <dl className="metrics metrics-3">
        <div>
          <dt>Bus ETA</dt>
          <dd>{formatEta(decision.etaMin)}</dd>
        </div>
        <div>
          <dt>Your walk</dt>
          <dd>{decision.walkMin} min</dd>
        </div>
        <div>
          <dt>Buffer</dt>
          <dd>{decision.bufferMin === null ? "—" : `${decision.bufferMin} min`}</dd>
        </div>
      </dl>
      <p className="confidence">
        <span className={`conf-dot conf-${decision.confidence.toLowerCase()}`} aria-hidden="true" />
        Confidence: <strong>{decision.confidence}</strong>
        <span className="muted"> · backend ETA; decision rule and walking time are interim</span>
      </p>
    </section>
  );
}
