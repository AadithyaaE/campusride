import type {
  ArrivalOut,
  AssignmentOut,
  BusStatus,
  CommuteDecision,
  CommuteDecisionOut,
  EtaPredictionOut,
  RouteStatus,
  StopBusOut,
  StopProximity,
} from "../../api/types";
import { DirectionTag, RouteChip } from "../../components/Badges";
import { countdownLabel, useWallClock, type SimReference } from "../../lib/countdown";
import { formatClock, formatDistance, stopsAwayText } from "../../lib/format";
import { hasEta, PROXIMITY_LABEL, STATUS_LABEL } from "./interim";

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

/** Display only: occupancy and the BACKEND's percentage (``services/capacity.py``). */
export function OccupancyBar({
  occupancy,
  capacity,
  percentage,
}: {
  occupancy: number;
  capacity: number;
  percentage: number | null;
}) {
  const pct = percentage ?? 0;
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
 * Route status (Feature 10) exactly as the backend evaluated it — never computed here.
 * States the observed condition only.
 */
export function RouteStatusText({
  status,
  distance,
}: {
  status: RouteStatus | null;
  distance: number | null;
}) {
  const m = distance === null ? null : Math.round(distance);
  if (status === "NORMAL") return <span className="route-ok">On planned route</span>;
  if (status === "MINOR_DEVIATION") {
    return (
      <span className="route-minor">Minor deviation{m !== null && ` · ${m} m off route`}</span>
    );
  }
  if (status === "MAJOR_DEVIATION") {
    return (
      <span className="route-major">
        Major deviation{m !== null && ` · ${m} m off route`}
        {m !== null && (
          <span className="route-alert" role="alert">
            Your bus is currently {m} m from its planned route.
          </span>
        )}
      </span>
    );
  }
  return <span className="muted">Route status unavailable</span>;
}

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
              <dt>Arrives at</dt>
              <dd>
                {hasEta(bus) && bus.eta.estimated_arrival_time
                  ? formatClock(bus.eta.estimated_arrival_time)
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
              <dt>Route</dt>
              <dd>
                <RouteStatusText status={bus.route_status} distance={bus.deviation_distance_m} />
              </dd>
            </div>
            <div className="metric-wide">
              <dt>Occupancy</dt>
              <dd>
                <OccupancyBar
                  occupancy={bus.occupancy}
                  capacity={bus.capacity}
                  percentage={bus.occupancy_percentage}
                />
                <span className="occ-detail" aria-label="Live occupancy">
                  {bus.occupancy} / {bus.capacity} passengers ·{" "}
                  {bus.occupancy_percentage === null
                    ? "—"
                    : `${bus.occupancy_percentage}% occupied`}{" "}
                  · {bus.available_seats} seat{bus.available_seats === 1 ? "" : "s"} available
                </span>
              </dd>
            </div>
          </dl>
          <p className="footnote">
            Boarding stop <strong>{assignment.boarding_stop.name}</strong>
            {bus.position.previous_stop && (
              <> · previous stop {bus.position.previous_stop.name}</>
            )}{" "}
            · {assignment.bus.reg_no} · Updated{" "}
            <time dateTime={bus.last_updated}>{formatClock(bus.last_updated)}</time>
          </p>
        </>
      )}
    </section>
  );
}

const VERDICT: Record<CommuteDecision, { label: string; icon: string; tone: string }> = {
  YES: { label: "YES", icon: "✓", tone: "yes" },
  RISK: { label: "RISK", icon: "⚠", tone: "risk" },
  MISSED: { label: "MISSED", icon: "✕", tone: "missed" },
  LOCATION_UNAVAILABLE: { label: "Location unavailable", icon: "?", tone: "unknown" },
  UNKNOWN: { label: "Can’t tell yet", icon: "?", tone: "unknown" },
};

const walkLabel = (min: number) => (min === 0 ? "<1 min" : `${min} min`);

/**
 * "Will I make my bus?" — renders the BACKEND decision as given
 * (`GET /students/me/commute-decision`). The browser never decides YES / RISK /
 * MISSED; it only ticks the bus countdown from the backend's arrival timestamp.
 */
export function DecisionCard({
  commute: d,
  simRef,
  onViewOptions,
}: {
  commute: CommuteDecisionOut;
  simRef: SimReference | null;
  onViewOptions?: () => void;
}) {
  const wallNow = useWallClock();
  const v = VERDICT[d.decision ?? "UNKNOWN"];
  const timed = d.decision === "YES" || d.decision === "RISK";
  const arrives =
    d.eta?.status === "at_stop"
      ? "At your stop now"
      : d.eta
        ? countdownLabel(d.eta, simRef, wallNow)
        : d.bus_eta_minutes !== null
          ? walkLabel(d.bus_eta_minutes)
          : "—";
  return (
    <section className={`live-card decision decision-${v.tone}`} aria-label="Will I make my bus?">
      <header className="live-card-head">
        <p className="eyebrow">Can I catch bus {d.bus_number}?</p>
        <SimTag label={d.student_location ? "Simulated location" : "Simulated"} />
      </header>
      <p className="decision-headline" role="status" aria-label={`Decision: ${v.label}`}>
        <span className="decision-icon" aria-hidden="true">
          {v.icon}
        </span>
        {v.label}
      </p>
      <p className="decision-detail">{d.reason}</p>
      {timed && (
        <dl className="metrics metrics-3">
          <div>
            <dt>Bus arrives in</dt>
            <dd aria-label={`Bus arrives in ${arrives}`}>{arrives}</dd>
          </div>
          <div>
            <dt>Walking time</dt>
            <dd>{d.walking_time_minutes === null ? "—" : walkLabel(d.walking_time_minutes)}</dd>
          </div>
          <div>
            <dt>Safety buffer</dt>
            <dd>{d.safety_buffer_minutes} min</dd>
          </div>
        </dl>
      )}
      {d.decision === "LOCATION_UNAVAILABLE" && (
        <p className="footnote">
          Location unavailable — we can’t estimate your walk, so there is no YES / RISK answer.
        </p>
      )}
      {(d.decision === "MISSED" || d.decision === "RISK") && d.alternatives_available > 0 && (
        <p className="decision-alt">
          {d.alternatives_available} other bus{d.alternatives_available === 1 ? "" : "es"} serve
          your stop.{" "}
          {onViewOptions && (
            <button type="button" className="link-button" onClick={onViewOptions}>
              See bus options
            </button>
          )}
        </p>
      )}
      <p className="footnote">
        {d.student_location && d.walking_distance_m !== null
          ? `Walk ≈ ${formatDistance(d.walking_distance_m)} from your demo location. `
          : ""}
        Estimated from your bus's live position. Your assigned bus stays {d.bus_number}.
      </p>
    </section>
  );
}
