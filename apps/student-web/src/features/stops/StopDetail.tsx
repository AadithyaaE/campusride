import { useCallback } from "react";

import { useApi } from "../../api/ApiContext";
import { Badge, DirectionTag, RouteChip, SharedBadge } from "../../components/Badges";
import { EmptyState, ErrorState, Loading, Phase2Notice } from "../../components/StateViews";
import type { Network } from "../../data/network";
import { useAsync } from "../../hooks/useAsync";
import { formatOffset, routeSort } from "../../lib/format";

interface Props {
  stopId: string;
  network: Network;
  myStopId: string | null;
  onSelectRoute: (routeId: string) => void;
}

/** Stop card. Serving routes come from `GET /stops/{id}/routes`. */
export function StopDetail({ stopId, network, myStopId, onSelectRoute }: Props) {
  const api = useApi();
  const load = useCallback(() => api.stopRoutes(stopId), [api, stopId]);
  const services = useAsync(load, stopId);
  const stop = network.stopById.get(stopId);

  if (!stop)
    return <EmptyState title="Stop not found">The backend has no stop {stopId}.</EmptyState>;

  const physical = network.servingRoutes.get(stopId) ?? [];
  const stopCount = (variantId: string) =>
    network.summaries.flatMap((r) => r.directions).find((d) => d.variant_id === variantId)
      ?.stop_count;

  return (
    <article className="detail" aria-labelledby="stop-title">
      <header className="detail-head">
        <p className="eyebrow">Stop · {stop.id}</p>
        <h2 id="stop-title">{stop.name}</h2>
        <div className="badge-row">
          {stop.is_campus_terminal && <Badge tone="brand">Campus terminal</Badge>}
          {network.sharedStopIds.has(stop.id) && <SharedBadge count={physical.length} />}
          {myStopId === stop.id && <Badge tone="brand">My boarding stop</Badge>}
        </div>
      </header>

      <section>
        <h3 className="section-title">Routes serving this stop</h3>
        {services.status === "loading" && <Loading label="Loading routes…" />}
        {services.status === "error" && (
          <ErrorState error={services.error} onRetry={services.reload} />
        )}
        {services.status === "success" &&
          (services.data.length === 0 ? (
            <EmptyState title="No routes serve this stop" />
          ) : (
            <ul className="list" aria-label="Routes serving this stop">
              {[...services.data]
                .sort((a, b) => routeSort(a.variant_id, b.variant_id))
                .map((s) => (
                  <li key={s.variant_id}>
                    <button
                      type="button"
                      className="list-row"
                      onClick={() => onSelectRoute(s.route_id)}
                    >
                      <RouteChip id={s.variant_id} color={s.color} />
                      <span className="row-main">
                        <span className="row-title">
                          {network.routeById.get(s.route_id)?.name ?? s.route_id}
                        </span>
                        <span className="row-sub">
                          <DirectionTag direction={s.direction} /> · stop {s.seq + 1}
                          {stopCount(s.variant_id) ? ` of ${stopCount(s.variant_id)}` : ""}
                        </span>
                      </span>
                      <span
                        className="row-meta"
                        title="Timetable time after the route's first stop — not a live ETA"
                      >
                        {formatOffset(s.scheduled_offset_s)}
                      </span>
                    </button>
                  </li>
                ))}
            </ul>
          ))}
        <p className="footnote">
          Times are the timetable offset from each route's first stop, not live arrival estimates.
        </p>
      </section>

      <Phase2Notice>
        Live buses approaching this stop will appear once telemetry is connected.
      </Phase2Notice>
    </article>
  );
}
