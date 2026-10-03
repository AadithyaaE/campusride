/**
 * My Bus — the student's COLLEGE-ASSIGNED bus, read-only.
 *
 * Source of truth: `GET /students/me/assignment`. Students never choose or
 * change their bus, route or boarding stop; the college transport office does.
 */
import { useCallback } from "react";

import { useApi } from "../../api/ApiContext";
import type { AssignmentOut, MyAssignmentOut } from "../../api/types";
import { DirectionTag, RouteChip } from "../../components/Badges";
import { ErrorState, Loading, Phase2Notice } from "../../components/StateViews";
import type { Network } from "../../data/network";
import { useAsync, type AsyncState } from "../../hooks/useAsync";
import { DIRECTION_LABEL, formatOffset, routeSort } from "../../lib/format";

interface Props {
  network: Network;
  assignment: AsyncState<MyAssignmentOut> & { reload: () => void };
  onShowOnMap: (routeId: string, stopId: string) => void;
}

export const UNASSIGNED_MESSAGE = "Your bus assignment is not available yet.";

export function MyBusPanel({ network, assignment, onShowOnMap }: Props) {
  return (
    <div className="panel-body">
      <h2 className="panel-title">My Bus</h2>
      {assignment.status === "loading" && <Loading label="Loading your bus assignment…" />}
      {assignment.status === "error" && (
        <ErrorState error={assignment.error} onRetry={assignment.reload} />
      )}
      {assignment.status === "success" &&
        (assignment.data.assignment === null ? (
          <Unassigned />
        ) : (
          <AssignedBus a={assignment.data.assignment} network={network} onShowOnMap={onShowOnMap} />
        ))}
    </div>
  );
}

function Unassigned() {
  return (
    <section className="state state-empty unassigned" aria-label="My bus">
      <strong>{UNASSIGNED_MESSAGE}</strong>
      <p>
        The college transport office assigns each student a bus and boarding stop. Once yours is
        assigned it will appear here automatically.
      </p>
    </section>
  );
}

function AssignedBus({
  a,
  network,
  onShowOnMap,
}: {
  a: AssignmentOut;
  network: Network;
  onShowOnMap: (routeId: string, stopId: string) => void;
}) {
  const api = useApi();
  const stopId = a.boarding_stop.stop_id;
  const load = useCallback(() => api.stopRoutes(stopId), [api, stopId]);
  const services = useAsync(load, stopId);

  const others = (services.data ?? [])
    .filter((s) => s.direction === a.route.direction && s.variant_id !== a.route.route_direction_id)
    .sort((x, y) => routeSort(x.variant_id, y.variant_id));

  return (
    <>
      <section
        className="mybus-card"
        style={{ ["--route-color" as string]: a.route.color }}
        aria-label="My bus"
      >
        <p className="eyebrow">My bus</p>
        <div className="mybus-head">
          <RouteChip id={a.route.route_direction_id} color={a.route.color} size="lg" />
          <div>
            <p className="mybus-route">{a.route.name}</p>
            <DirectionTag direction={a.route.direction} />
          </div>
        </div>
        <dl className="facts">
          <div>
            <dt>Bus</dt>
            <dd>
              <strong>{a.bus.id}</strong>
              <span className="muted"> · {a.bus.reg_no}</span>
            </dd>
          </div>
          <div>
            <dt>Direction</dt>
            <dd>{DIRECTION_LABEL[a.route.direction]}</dd>
          </div>
          <div>
            <dt>Boarding stop</dt>
            <dd>
              {a.boarding_stop.name}
              <span className="muted">
                {" "}
                · stop {a.boarding_stop.seq + 1} of {a.boarding_stop.stop_count}
              </span>
            </dd>
          </div>
          <div>
            <dt>Timetable</dt>
            <dd>{formatOffset(a.boarding_stop.scheduled_offset_s)} after the route’s first stop</dd>
          </div>
        </dl>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => onShowOnMap(a.route.route_id, stopId)}
        >
          Show on map
        </button>
        <p className="footnote">
          Assigned by your college transport office. Contact them to change your bus or stop.
        </p>
      </section>

      <Phase2Notice>
        Live position of bus {a.bus.id} appears here once telemetry is connected.
      </Phase2Notice>

      <section>
        <h3 className="section-title">Other routes at {a.boarding_stop.name}</h3>
        {services.status === "loading" && <Loading label="Loading routes…" />}
        {services.status === "error" && (
          <ErrorState error={services.error} onRetry={services.reload} />
        )}
        {services.status === "success" &&
          (others.length === 0 ? (
            <p className="footnote">
              No other route serves this stop {DIRECTION_LABEL[a.route.direction].toLowerCase()}.
            </p>
          ) : (
            <ul className="list" aria-label="Other routes at my stop">
              {others.map((s) => (
                <li key={s.variant_id} className="list-row static">
                  <RouteChip id={s.variant_id} color={s.color} />
                  <span className="row-main">
                    <span className="row-title">
                      {network.routeById.get(s.route_id)?.name ?? s.route_id}
                    </span>
                    <span className="row-sub">{s.label}</span>
                  </span>
                  <span className="row-meta">{formatOffset(s.scheduled_offset_s)}</span>
                </li>
              ))}
            </ul>
          ))}
      </section>
    </>
  );
}
