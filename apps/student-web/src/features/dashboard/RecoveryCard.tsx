/**
 * Missed-bus recovery card (Feature 9) — renders `GET /students/me/recovery-options` as given.
 *
 * The backend decides WHEN recovery applies (trigger), WHICH buses qualify (same
 * stop and direction, catchable, not full/stale/passed) and their ORDER. The card
 * only words the trigger and shows the values. A suggestion is never a
 * reassignment: the college-assigned bus stays the student's bus.
 */
import type { RecoveryOptionOut, RecoveryOut } from "../../api/types";
import type { SimReference } from "../../lib/countdown";
import { EtaCountdown, SimTag } from "./LiveCards";

type Trigger = NonNullable<RecoveryOut["trigger"]>;

const HEADLINE: Record<Trigger, (bus: string) => string> = {
  likely_to_miss: (bus) => `You may miss ${bus}`,
  missed: (bus) => `You missed ${bus}`,
  significantly_delayed: (bus) => `${bus} is delayed`,
};

/** Shown only when the backend found a reason for recovery. */
const showsRecovery = (r: RecoveryOut | null): r is RecoveryOut =>
  !!r && (r.status === "recovery_available" || r.status === "no_alternative") && !!r.trigger;

const statusText = (o: RecoveryOptionOut) =>
  o.status === "on_time" ? "On time" : `Delayed +${o.delay_minutes} min`;

export function RecoveryCard({
  recovery: r,
  simRef,
  onViewOptions,
}: {
  recovery: RecoveryOut;
  simRef: SimReference | null;
  onViewOptions?: () => void;
}) {
  if (!showsRecovery(r)) return null;
  const trigger = r.trigger as Trigger;
  const mine = r.assigned_bus ?? "your bus";
  const rec = r.recommended;
  return (
    <section className={`live-card recovery recovery-${trigger}`} aria-label="Missed-bus recovery">
      <header className="live-card-head">
        <p className="eyebrow">Recovery</p>
        <SimTag label="Suggestion" />
      </header>
      <h3 className="recovery-headline" role="status">
        {HEADLINE[trigger](mine)}
        {trigger === "significantly_delayed" && r.assigned_bus_delay_minutes !== null && (
          <span className="recovery-delay"> +{r.assigned_bus_delay_minutes} min</span>
        )}
      </h3>
      {rec ? (
        <>
          <p className="recovery-try">
            {trigger === "significantly_delayed" ? "Consider" : "Try"}{" "}
            <strong>BUS {rec.bus_number}</strong>
            {trigger === "significantly_delayed" ? "" : " instead"}
          </p>
          <dl className="recovery-facts">
            <div>
              <dt>ETA</dt>
              <dd>
                <EtaCountdown eta={rec.eta} simRef={simRef} showMeta={false} />
              </dd>
            </div>
            <div>
              <dt>Occupancy</dt>
              <dd aria-label="Recommended bus occupancy">
                {rec.occupancy} / {rec.capacity} passengers
                <span className="sub">
                  {rec.occupancy_percentage === null
                    ? "—"
                    : `${rec.occupancy_percentage}% occupied`}{" "}
                  · {rec.available_seats} seat{rec.available_seats === 1 ? "" : "s"} available
                </span>
              </dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{statusText(rec)}</dd>
            </div>
          </dl>
          <p className="recovery-reason">“{rec.reason}”</p>
          {r.alternatives.length > 0 && (
            <div className="recovery-more">
              <p className="eyebrow">Other recovery options</p>
              <ul aria-label="Other recovery options">
                {r.alternatives.map((o) => (
                  <li key={o.bus_id} aria-label={`Recovery option BUS ${o.bus_number}`}>
                    <strong>BUS {o.bus_number}</strong>
                    <EtaCountdown eta={o.eta} simRef={simRef} showMeta={false} />
                    <span>
                      {o.available_seats} seat{o.available_seats === 1 ? "" : "s"}
                    </span>
                    <span className="muted">{statusText(o)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : (
        <p className="recovery-none">
          No other bus serving {r.boarding_stop_name ?? "your stop"} can be caught right now.
        </p>
      )}
      {onViewOptions && (
        <button type="button" className="btn btn-block" onClick={onViewOptions}>
          View bus options
        </button>
      )}
      <p className="footnote">
        Suggestion only — your college-assigned bus stays {mine}. Every option serves{" "}
        {r.boarding_stop_name ?? "your stop"} in your direction.
      </p>
    </section>
  );
}
