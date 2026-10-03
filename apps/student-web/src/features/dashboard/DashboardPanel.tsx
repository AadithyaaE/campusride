/**
 * Student Dashboard (home).
 *
 * BACKEND: the college-assigned bus / route direction / boarding stop
 *   (`GET /students/me/assignment`), live bus state (`GET /buses`), stop matching
 *   and ETAs (`GET /students/me/arrivals`), the multi-bus comparison
 *   (`GET /students/me/bus-options`) — polled, see data/liveFleet.ts.
 *   and "Will I make my bus?" (`GET /students/me/commute-decision`).
 * INTERIM (interim.ts): alerts —
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
import type { DashboardAlert } from "./interim";
import { DecisionCard, MyBusLiveCard } from "./LiveCards";
import { QuickActions } from "./QuickActions";

type Loadable<T> = AsyncState<T> & { reload: () => void };

/** Interim estimates layered on the backend's matching / ETA / comparison results. */
export interface DashboardData {
  /** Other buses serving the boarding stop, in the backend's ETA order. */
  atMyStop: ArrivalOut[];
  alerts: DashboardAlert[];
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
        <Loading label="Loading your bus assignment…" />
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
  const demo = <DemoControls sim={fleet.sim} control={fleet.control} />;

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
        <Loading label="Loading live bus data…" />
      ) : (
        <>
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
            onViewStop={() => props.onViewStop(a.boarding_stop.stop_id)}
            onViewAllBuses={props.onViewAllBuses}
            onViewRoute={() => props.onViewRoute(a.route.route_id)}
          />
          <AlertsList alerts={data.alerts} />
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

function Body({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="panel-body dashboard">
      {title && <h2 className="panel-title">{title}</h2>}
      {children}
    </div>
  );
}
