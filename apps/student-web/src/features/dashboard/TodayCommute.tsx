/**
 * TODAY'S COMMUTE (Feature 16, polished in 16.5) — the backend's single answer from
 * `GET /students/me/commute`: phase, assigned bus/route/stop, ETA, "Will I make it?",
 * occupancy, boarding and alerts. Labels and layout only — the phase, decision, ETA and
 * occupancy are never computed here.
 */
import type { CommutePhase, EtaPredictionOut, StudentCommuteOut } from "../../api/types";
import { DirectionTag, RouteChip } from "../../components/Badges";
import { Icon } from "../../components/Icon";
import type { SimReference } from "../../lib/countdown";
import { formatClock } from "../../lib/format";
import { EtaCountdown, OccupancyBar } from "./LiveCards";

const PHASE: Record<CommutePhase, { label: string; tone: string }> = {
  unassigned: { label: "No bus assigned", tone: "muted" },
  no_trip: { label: "No active trip", tone: "muted" },
  waiting: { label: "Waiting", tone: "info" },
  approaching: { label: "Approaching", tone: "warn" },
  at_stop: { label: "At your stop", tone: "go" },
  on_board: { label: "On board", tone: "ok" },
  completed: { label: "Completed", tone: "ok" },
  missed: { label: "Missed", tone: "bad" },
  recovery_available: { label: "Alternative available", tone: "bad" },
};

/** The backend's decision, in words (its own reason sentence is shown underneath). */
const DECISION: Record<string, { label: string; tone: string }> = {
  YES: { label: "You'll make it", tone: "ok" },
  RISK: { label: "At risk", tone: "warn" },
  MISSED: { label: "Missed", tone: "bad" },
  LOCATION_UNAVAILABLE: { label: "Can't tell yet", tone: "muted" },
  UNKNOWN: { label: "Can't tell yet", tone: "muted" },
};

export interface TodayActions {
  onShowBus: () => void;
  onViewRecovery: () => void;
  onViewOptions: () => void;
}

export function TodayCommute({
  today,
  heroEta,
  simRef,
  actions,
}: {
  today: StudentCommuteOut;
  /** The backend ETA to show big (the same prediction the bus card counts down from). */
  heroEta: EtaPredictionOut | null;
  simRef: SimReference | null;
  actions: TodayActions;
}) {
  const { assignment: a, bus, decision: d, boarding: b, phase } = today;
  const live = bus?.live ?? null;
  const p = PHASE[phase];
  const boarded = b.boarded;
  const onBoard = phase === "on_board" || phase === "completed";
  const decision = d.decision ? DECISION[d.decision] : undefined;
  const action =
    phase === "recovery_available"
      ? { label: "View recovery options", run: actions.onViewRecovery }
      : phase === "missed"
        ? { label: "See other buses", run: actions.onViewOptions }
        : ["waiting", "approaching", "at_stop", "on_board"].includes(phase)
          ? { label: "Show my bus on the map", run: actions.onShowBus }
          : null;

  return (
    <section className={`today today-${p.tone}`} aria-label="Today's commute">
      <header className="today-head">
        <p className="eyebrow">Today&apos;s commute</p>
        <span className={`phase-badge phase-${p.tone}`} role="status">
          {p.label}
        </span>
      </header>

      {a && (
        <>
          <div className="today-bus">
            <span className="today-bus-icon" style={{ background: a.route.color }}>
              <Icon name="bus" size={22} />
            </span>
            <div>
              <p className="today-bus-title">Bus {a.bus.id}</p>
              <p className="today-route">
                <RouteChip id={a.route.route_direction_id} color={a.route.color} />
                <span>{a.route.name}</span>
                <DirectionTag direction={a.route.direction} />
              </p>
            </div>
          </div>
          <p className="today-stop">
            <Icon name="pin" size={16} />
            <span>
              Boarding at <strong>{a.boarding_stop.name}</strong>
            </span>
          </p>

          <div className="today-hero">
            <div className="today-eta">
              <span className="today-eta-label">
                <Icon name="clock" size={15} /> Arrives at your stop
              </span>
              {heroEta && !onBoard && today.trip?.status !== "completed" ? (
                <EtaCountdown eta={heroEta} simRef={simRef} size="lg" showMeta={false} />
              ) : (
                <span className="today-eta-none">
                  {phase === "completed"
                    ? "Trip complete"
                    : onBoard
                      ? "You're on board"
                      : today.trip?.status === "completed"
                        ? "Trip ended"
                        : "—"}
                </span>
              )}
            </div>
            <div className={`today-decision tone-${onBoard ? "ok" : (decision?.tone ?? "muted")}`}>
              <span className="today-eta-label">Will I make it?</span>
              <strong>{onBoard ? "Boarded" : (decision?.label ?? "Can't tell yet")}</strong>
              <span className="today-decision-why">
                {onBoard
                  ? boarded
                    ? `Boarded · ${formatClock(boarded.timestamp)}`
                    : today.phase_reason
                  : d.reason}
              </span>
            </div>
          </div>

          <dl className="today-facts">
            <div>
              <dt>
                <Icon name="users" size={15} /> Occupancy
              </dt>
              <dd>
                {live && bus ? (
                  <>
                    <OccupancyBar
                      occupancy={live.occupancy}
                      capacity={bus.capacity}
                      percentage={live.occupancy_percentage}
                    />
                    <span className="today-seats">
                      {live.available_seats === null
                        ? `${live.occupancy} / ${bus.capacity} passengers`
                        : live.available_seats > 0
                          ? `${live.available_seats} seats available`
                          : "No seats available"}
                    </span>
                  </>
                ) : (
                  "Not available yet"
                )}
              </dd>
            </div>
            <div>
              <dt>
                <Icon name="ticket" size={15} /> Boarding
              </dt>
              <dd>
                {boarded
                  ? `Boarded · ${formatClock(boarded.timestamp)}`
                  : b.ready
                    ? "Ready — scan when you board"
                    : "Not boarded"}
              </dd>
            </div>
          </dl>
        </>
      )}

      <p className="today-reason">{today.phase_reason}</p>

      {today.alerts.length > 0 && (
        <p className="today-alert" role="note">
          <Icon name="alert" size={16} />
          <span>
            {today.alerts[0]!.message}
            {today.alerts.length > 1 && (
              <span className="muted"> · +{today.alerts.length - 1} more</span>
            )}
          </span>
        </p>
      )}

      {action ? (
        <button type="button" className="btn btn-primary btn-block" onClick={action.run}>
          {action.label}
        </button>
      ) : (
        <p className="today-idle">This updates automatically when your bus starts its next trip.</p>
      )}
    </section>
  );
}
