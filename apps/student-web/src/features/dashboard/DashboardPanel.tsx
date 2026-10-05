/**
 * Student Dashboard (home).
 *
 * BACKEND: the college-assigned bus / route direction / boarding stop
 *   (`GET /students/me/assignment`), live bus state (`GET /buses`), stop matching
 *   and ETAs (`GET /students/me/arrivals`), the multi-bus comparison
 *   (`GET /students/me/bus-options`) — polled, see data/liveFleet.ts.
 *   "Will I make my bus?" (`GET /students/me/commute-decision`) and missed-bus
 *   recovery (`GET /students/me/recovery-options`, suggestions only).
 * Alerts (`GET /alerts`, Feature 11) come from the backend AlertService.
 * Feature 16: TODAY'S COMMUTE (`GET /students/me/commute`, the backend's phase + decision +
 *   boarding in one answer) leads the page; RECENT COMMUTES (`GET /students/me/history`)
 *   follows the alerts.
 *   labelled as estimates until Phases 4/6 provide them from the backend.
 */
import type { ReactNode } from "react";

import type { ArrivalOut, MyAssignmentOut } from "../../api/types";
import { ErrorState, Loading } from "../../components/StateViews";
import type { LiveFleet } from "../../data/liveFleet";
import type { Network } from "../../data/network";
import type { AsyncState } from "../../hooks/useAsync";
import { UNASSIGNED_MESSAGE } from "../mybus/MyBusPanel";
import { AlertsList } from "./AlertsList";
import { BusList, type BusView } from "./BusList";
import { BusOptions } from "./BusOptions";
import { DemoControls } from "./DemoControls";
import { DecisionCard, MyBusLiveCard } from "./LiveCards";
import { QuickActions } from "./QuickActions";
import { RecentCommutes } from "./RecentCommutes";
import { RecoveryCard } from "./RecoveryCard";
import { hasEta } from "./interim";
import { TodayCommute } from "./TodayCommute";

type Loadable<T> = AsyncState<T> & { reload: () => void };

/** Interim estimates layered on the backend's matching / ETA / comparison results. */
export interface DashboardData {
  /** Other buses serving the boarding stop, in the backend's ETA order. */
  atMyStop: ArrivalOut[];
}

interface Props {
  firstName: string;
  network: Network;
  assignment: Loadable<MyAssignmentOut>;
  fleet: LiveFleet;
  data: DashboardData;
  busView: BusView;
  onBusViewChange: (v: BusView) => void;
  /** Bus highlighted on the map from a comparison card (null = none). */
  selectedBusId: string | null;
  onSelectBus: (busId: string | null) => void;
  onViewStop: (stopId: string) => void;
  onViewRoute: (routeId: string) => void;
  onViewAllBuses: () => void;
}

export function DashboardPanel(props: Props) {
  const { assignment, fleet, data, network } = props;

  if (assignment.status === "loading") {
    return (
      <Body>
        <Loading label="Getting your bus assignment…" />
      </Body>
    );
  }
  if (assignment.status === "error") {
    return (
      <Body>
        <ErrorState error={assignment.error} onRetry={assignment.reload} />
      </Body>
    );
  }

  const a = assignment.data.assignment;
  // Simulator controls are an operator tool, not part of the student product: only with ?demo.
  const demo = showDemoControls() ? (
    <DemoControls sim={fleet.sim} control={fleet.control} realtime={fleet.realtime} />
  ) : null;

  if (a === null) {
    return (
      <Body title={`Hi, ${props.firstName}`}>
        <section className="state state-empty unassigned" aria-label="My bus">
          <strong>{UNASSIGNED_MESSAGE}</strong>
          <p>
            Your college transport office needs to assign you a bus and boarding stop. Once they do,
            your bus, live status and alerts will appear here automatically. You can’t choose a bus
            yourself.
          </p>
        </section>
        {demo}
      </Body>
    );
  }

  const arrivals = fleet.arrivals?.status === "assigned" ? fleet.arrivals : null;
  const paused = fleet.sim?.paused ?? false;
  const simRef =
    fleet.fetchedAt && fleet.sim
      ? { fetchedAtMs: fleet.fetchedAt.getTime(), speed: fleet.sim.speed, paused }
      : null;
  return (
    <Body title={`Hi, ${props.firstName}`}>
      {fleet.error && !fleet.buses && <ErrorState error={fleet.error} onRetry={fleet.refresh} />}
      {!fleet.buses && !fleet.error ? (
        <Loading label="Getting your latest commute…" />
      ) : (
        <>
          {fleet.today && fleet.today.status === "assigned" && (
            <TodayCommute
              today={fleet.today}
              heroEta={
                arrivals?.my_bus_serving_stop && arrivals.my_bus && hasEta(arrivals.my_bus)
                  ? arrivals.my_bus.eta
                  : (fleet.today.decision.eta ?? null)
              }
              simRef={simRef}
              actions={{
                onShowBus: () => {
                  props.onSelectBus(a.bus.id);
                  document.querySelector(".map-wrap")?.scrollIntoView?.({ behavior: "smooth" });
                },
                onViewRecovery: () =>
                  document
                    .getElementById("recovery")
                    ?.scrollIntoView?.({ behavior: "smooth", block: "start" }),
                onViewOptions: () =>
                  document
                    .getElementById("bus-options")
                    ?.scrollIntoView?.({ behavior: "smooth", block: "start" }),
              }}
            />
          )}
          {/* The backend's own boarding record wins: no "you missed it" card once boarded. */}
          {fleet.recovery && !fleet.today?.boarding.boarded && (
            <RecoveryCard
              recovery={fleet.recovery}
              simRef={simRef}
              onViewOptions={() =>
                document
                  .getElementById("bus-options")
                  ?.scrollIntoView?.({ behavior: "smooth", block: "start" })
              }
            />
          )}
          <MyBusLiveCard
            assignment={a}
            bus={arrivals?.my_bus ?? null}
            servingStop={arrivals?.my_bus_serving_stop ?? false}
            paused={paused}
            simRef={simRef}
          />
          {fleet.commute?.status === "assigned" && (
            <DecisionCard
              commute={fleet.commute}
              simRef={simRef}
              onViewOptions={() =>
                document
                  .getElementById("bus-options")
                  ?.scrollIntoView?.({ behavior: "smooth", block: "start" })
              }
            />
          )}
          {fleet.options?.status === "assigned" && (
            <BusOptions
              options={fleet.options}
              simRef={simRef}
              selectedBusId={props.selectedBusId}
              onSelectBus={props.onSelectBus}
            />
          )}
          <QuickActions
            busId={a.bus.id}
            simNowIso={fleet.sim?.sim_time ?? null}
            onBoarded={() => void fleet.refresh()}
            onViewStop={() => props.onViewStop(a.boarding_stop.stop_id)}
            onViewAllBuses={props.onViewAllBuses}
            onViewRoute={() => props.onViewRoute(a.route.route_id)}
          />
          <AlertsList
            alerts={fleet.alerts ?? []}
            nowIso={fleet.sim?.sim_time ?? null}
            onMarkRead={(id) => void fleet.markAlertRead(id)}
          />
          <RecentCommutes
            refreshKey={[
              fleet.today?.phase,
              fleet.today?.trip?.trip_id,
              fleet.today?.trip?.status,
              fleet.today?.boarding.boarded?.boarding_id,
            ].join("|")}
          />
          <BusList
            view={props.busView}
            onViewChange={props.onBusViewChange}
            atMyStop={data.atMyStop}
            simRef={simRef}
            allBuses={fleet.buses ?? []}
            assignedBusId={a.bus.id}
            boardingStopName={a.boarding_stop.name}
            network={network}
          />
        </>
      )}
      {demo}
    </Body>
  );
}

function showDemoControls(): boolean {
  try {
    return new URLSearchParams(window.location.search).has("demo");
  } catch {
    return false;
  }
}

function Body({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="panel-body dashboard">
      {title && <h2 className="panel-title">{title}</h2>}
      {children}
    </div>
  );
}
