import type { ArrivalOut, BusOut } from "../../api/types";
import { DirectionTag, RouteChip } from "../../components/Badges";
import { EmptyState } from "../../components/StateViews";
import type { Network } from "../../data/network";
import type { SimReference } from "../../lib/countdown";
import { formatDistance, stopsAwayText } from "../../lib/format";
import {
  EtaCountdown,
  OccupancyBar,
  ProximityChip,
  ScheduleChip,
  SimTag,
  StatusChip,
} from "./LiveCards";

export type BusView = "stop" | "all";

interface Props {
  view: BusView;
  onViewChange: (v: BusView) => void;
  /** Backend-matched buses serving the boarding stop (excluding my bus), in backend ETA order. */
  atMyStop: ArrivalOut[];
  simRef: SimReference | null;
  allBuses: BusOut[];
  assignedBusId: string;
  boardingStopName: string;
  network: Network;
}

/** Read-only. Other buses are information only — the assignment never changes here. */
export function BusList({
  view,
  onViewChange,
  atMyStop,
  simRef,
  allBuses,
  assignedBusId,
  boardingStopName,
  network,
}: Props) {
  const live = allBuses.filter((b) => b.live);
  return (
    <section id="buses" aria-label="Buses">
      <header className="section-head">
        <h3 className="section-title">
          {view === "stop" ? `Other buses serving ${boardingStopName}` : "All buses"}
        </h3>
        <SimTag />
      </header>
      <div className="segmented segmented-sm" role="tablist" aria-label="Which buses">
        <button
          type="button"
          role="tab"
          aria-selected={view === "stop"}
          className={view === "stop" ? "is-active" : ""}
          onClick={() => onViewChange("stop")}
        >
          At my stop ({atMyStop.length})
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "all"}
          className={view === "all" ? "is-active" : ""}
          onClick={() => onViewChange("all")}
        >
          All buses ({live.length})
        </button>
      </div>

      {view === "stop" ? (
        atMyStop.length === 0 ? (
          <EmptyState title="No other bus serves your stop in your direction right now" />
        ) : (
          <ul className="list" aria-label="Other buses at my stop">
            {atMyStop.map((bus) => (
              <li key={bus.bus_id} className="bus-row">
                <div className="bus-row-main">
                  <span className="bus-id">{bus.bus_number}</span>
                  <span className="row-main">
                    <span className="row-title">
                      <RouteChip
                        id={bus.route_direction_id}
                        color={routeColor(network, bus.route_id)}
                      />{" "}
                      {bus.route_name}
                    </span>
                    <span className="row-sub">
                      <DirectionTag direction={bus.direction} /> ·{" "}
                      <StatusChip status={bus.status} /> <ScheduleChip bus={bus} />
                    </span>
                    <span className="row-sub">
                      Current: {bus.position.current_stop.name} · Next:{" "}
                      {bus.position.next_stop?.name ?? "—"}
                    </span>
                    {bus.match && (
                      <span className="row-sub">
                        <ProximityChip proximity={bus.match.proximity} />{" "}
                        {bus.match.proximity !== "passed_stop" &&
                          `${formatDistance(bus.match.distance_to_stop_m)} to my stop`}
                        {stopsAwayText(bus.match.stops_away) &&
                          ` · ${stopsAwayText(bus.match.stops_away)}`}
                      </span>
                    )}
                    <OccupancyBar
                      occupancy={bus.occupancy}
                      capacity={bus.capacity}
                      percentage={bus.occupancy_percentage}
                    />
                  </span>
                  <span className="bus-eta">
                    <EtaCountdown eta={bus.eta} simRef={simRef} />
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )
      ) : (
        <ul className="list" aria-label="All buses">
          {live.map((b) => (
            <li key={b.id} className={`bus-row${b.id === assignedBusId ? " is-mine" : ""}`}>
              <div className="bus-row-main">
                <span className="bus-id">{b.id}</span>
                <span className="row-main">
                  <span className="row-title">
                    <RouteChip
                      id={b.live!.route_direction_id ?? b.route_id}
                      color={routeColor(network, b.route_id)}
                    />{" "}
                    {network.routeById.get(b.route_id)?.name ?? b.route_id}
                    {b.id === assignedBusId && <span className="mine-tag">My bus</span>}
                  </span>
                  <span className="row-sub">
                    {b.live!.direction && <DirectionTag direction={b.live!.direction} />} ·{" "}
                    <StatusChip status={b.live!.status} /> <ScheduleChip bus={b.live!} />
                  </span>
                  <span className="row-sub">Next: {stopName(network, b.live!.next_stop_id)}</span>
                  <OccupancyBar
                    occupancy={b.live!.occupancy}
                    capacity={b.capacity}
                    percentage={b.live!.occupancy_percentage}
                  />
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="footnote">
        Your assigned bus is set by the college transport office and can’t be changed here. ETAs and
        the bus comparison come from the backend.
      </p>
    </section>
  );
}

const routeColor = (network: Network, routeId: string) =>
  network.routeById.get(routeId)?.color ?? "#475569";

const stopName = (network: Network, id: string | null | undefined) =>
  (id && network.stopById.get(id)?.name) || "—";
