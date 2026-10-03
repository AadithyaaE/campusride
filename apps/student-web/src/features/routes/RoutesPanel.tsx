import { useState } from "react";

import type { Direction, RouteDetailOut } from "../../api/types";
import { DirectionTag, RouteChip } from "../../components/Badges";
import { EmptyState, Phase2Notice } from "../../components/StateViews";
import type { Network } from "../../data/network";
import { DIRECTION_LABEL, formatKm, formatOffset } from "../../lib/format";

interface Props {
  network: Network;
  selectedRouteId: string | null;
  myStopId: string | null;
  defaultDirection: Direction;
  onSelectRoute: (routeId: string | null) => void;
  onSelectStop: (stopId: string) => void;
}

export function RoutesPanel(props: Props) {
  const { network, selectedRouteId, onSelectRoute } = props;
  const route = selectedRouteId ? network.routeById.get(selectedRouteId) : undefined;

  if (selectedRouteId) {
    return (
      <div className="panel-body">
        <button type="button" className="link-back" onClick={() => onSelectRoute(null)}>
          ← All routes
        </button>
        {route ? (
          <RouteDetail key={route.id} route={route} {...props} />
        ) : (
          <EmptyState title="Route not found">
            The backend has no route {selectedRouteId}.
          </EmptyState>
        )}
      </div>
    );
  }

  return (
    <div className="panel-body">
      <h2 className="panel-title">Routes</h2>
      {network.summaries.length === 0 ? (
        <EmptyState title="No routes">
          The backend returned no routes. Has the database been seeded?
        </EmptyState>
      ) : (
        <ul className="list" aria-label="All routes">
          {network.routes.map((r) => {
            const summary = network.summaries.find((s) => s.id === r.id);
            const to = r.directions.find((d) => d.direction === "to_campus");
            return (
              <li key={r.id}>
                <button
                  type="button"
                  className="list-row route-row"
                  onClick={() => onSelectRoute(r.id)}
                >
                  <RouteChip id={r.id} color={r.color} />
                  <span className="row-main">
                    <span className="row-title">{r.name}</span>
                    <span className="row-sub">
                      {to ? `${to.stops[0]?.name ?? "?"} ⇄ Campus` : ""} · {formatKm(r.length_m)}
                    </span>
                  </span>
                  <span className="row-meta">
                    {summary?.directions[0]?.stop_count ?? "–"} stops
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function RouteDetail({
  route,
  network,
  myStopId,
  defaultDirection,
  onSelectStop,
}: Props & { route: RouteDetailOut }) {
  const available = route.directions.map((d) => d.direction);
  const [direction, setDirection] = useState<Direction>(
    available.includes(defaultDirection) ? defaultDirection : (available[0] ?? "to_campus"),
  );
  const dir = route.directions.find((d) => d.direction === direction);

  return (
    <article className="detail" aria-labelledby="route-title">
      <header className="detail-head">
        <p className="eyebrow">Route</p>
        <h2 id="route-title" className="title-with-chip">
          <RouteChip id={route.id} color={route.color} size="lg" />
          {route.name}
        </h2>
        <p className="muted">
          {formatKm(route.length_m)} · {route.directions.length} directions · same road both ways
        </p>
      </header>

      <div className="segmented" role="tablist" aria-label="Direction">
        {route.directions.map((d) => (
          <button
            key={d.variant_id}
            type="button"
            role="tab"
            aria-selected={d.direction === direction}
            className={d.direction === direction ? "is-active" : ""}
            onClick={() => setDirection(d.direction)}
          >
            {d.variant_id} · {DIRECTION_LABEL[d.direction]}
          </button>
        ))}
      </div>

      {dir && (
        <section>
          <h3 className="section-title">
            {dir.label} · {dir.stops.length} stops
          </h3>
          <ol className="timeline" aria-label={`Stops on ${dir.label}`}>
            {dir.stops.map((s) => {
              const shared = network.sharedStopIds.has(s.stop_id);
              const terminal = network.stopById.get(s.stop_id)?.is_campus_terminal;
              return (
                <li key={s.stop_id} style={{ ["--route-color" as string]: route.color }}>
                  <button
                    type="button"
                    className="timeline-row"
                    onClick={() => onSelectStop(s.stop_id)}
                  >
                    <span
                      className={`timeline-dot${shared ? " is-shared" : ""}${terminal ? " is-terminal" : ""}`}
                    />
                    <span className="row-main">
                      <span className="row-title">
                        {s.name}
                        {s.stop_id === myStopId && <span className="mine-tag">My stop</span>}
                      </span>
                      {shared && (
                        <span className="row-sub">
                          Shared with{" "}
                          {(network.servingRoutes.get(s.stop_id) ?? [])
                            .filter((r) => r !== route.id)
                            .join(", ")}
                        </span>
                      )}
                    </span>
                    <span className="row-meta">{formatOffset(s.scheduled_offset_s)}</span>
                  </button>
                </li>
              );
            })}
          </ol>
          <p className="footnote">
            <DirectionTag direction={dir.direction} /> Times are the timetable from the first stop,
            not live ETAs.
          </p>
        </section>
      )}

      <Phase2Notice>
        Buses running on this route will be shown live once the simulator is connected.
      </Phase2Notice>
    </article>
  );
}
