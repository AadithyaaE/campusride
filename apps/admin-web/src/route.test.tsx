import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApi, type BusOut, type RouteStatusResponse } from "./api/client";
import { FleetOccupancy } from "./FleetOccupancy";
import type { RouteMapProps } from "./RouteMap";

const mapProps: { current: RouteMapProps | null } = { current: null };
vi.mock("./RouteMap", () => ({
  default: (p: RouteMapProps) => {
    mapProps.current = p;
    return <div data-testid="route-map" />;
  },
}));

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const ROUTE: [number, number][] = [
  [80.2, 12.9],
  [80.21, 12.91],
  [80.22, 12.92],
];

type Live = NonNullable<BusOut["live"]>;

function bus(
  id: string,
  route_status: Live["route_status"],
  deviation_distance_m: number | null,
): BusOut {
  return {
    id,
    reg_no: `TN ${id}`,
    capacity: 50,
    route_id: "R3",
    status: "active",
    source: "sim",
    live: {
      trip_id: `T-${id}`,
      route_id: "R3",
      route_direction_id: "R3",
      direction: "to_campus",
      location: { type: "Point", coordinates: [80.21, 12.91] },
      speed_mps: 8,
      heading_deg: 0,
      status: route_status === "MAJOR_DEVIATION" ? "deviated" : "en_route",
      schedule_status: "on_time",
      delay_s: 0,
      current_stop_id: "S20",
      next_stop_id: "S21",
      route_progress: 0.4,
      distance_along_m: 4000,
      occupancy: 20,
      available_seats: 30,
      occupancy_percentage: 40,
      boarded_count: 0,
      route_status,
      deviation_distance_m,
      last_updated: "2026-10-05T02:10:00Z",
      stale: false,
    },
  };
}

function routeStatus(over: Partial<RouteStatusResponse> = {}): RouteStatusResponse {
  return {
    bus_id: "B05",
    trip_id: "T-B05",
    route_id: "R3",
    route_direction_id: "R3",
    route_status: "MAJOR_DEVIATION",
    deviation_distance_m: 312.4,
    thresholds: { minor_m: 50, major_m: 150 },
    expected_route: { type: "LineString", coordinates: ROUTE },
    current_location: { lat: 12.915, lon: 80.214 },
    nearest_route_point: { lat: 12.912, lon: 80.212 },
    timestamp: "2026-10-05T02:10:00Z",
    evaluated_at: "2026-10-05T02:10:02Z",
    source: "synthetic",
    major_alert_active: true,
    message: "BUS B05 is 312 m off its planned route.",
    ...over,
  };
}

function setup(rs: RouteStatusResponse = routeStatus()) {
  const calls: { key: string; body: unknown }[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const url = new URL(String(input));
    const key = `${init?.method ?? "GET"} ${url.pathname}${url.search}`;
    const body: unknown = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ key, body });
    if (key === "GET /api/v1/buses") {
      return json([
        bus("B05", "MAJOR_DEVIATION", 312.4),
        bus("B06", "MINOR_DEVIATION", 92.8),
        bus("B07", "NORMAL", 6.1),
      ]);
    }
    if (key === "GET /api/v1/buses/B05/route-status") return json(rs);
    if (key === "GET /api/v1/alerts?active=true") {
      return json([
        {
          id: "ALERT-1",
          type: "deviation",
          severity: "critical",
          title: "BUS B05 major route deviation",
          body: "BUS B05 is 312 m off its planned route.",
          payload: { bus_id: "B05" },
          created_at: "2026-10-05T02:09:30Z",
          resolved_at: null,
          active: true,
        },
      ]);
    }
    if (key === "POST /api/v1/sim/route-deviation") {
      const mode = (body as { mode: string }).mode;
      return json({ enabled: true, route_deviation: mode === "normal" ? {} : { B05: mode } });
    }
    return json({ error: { code: "not_found", message: key } }, 404);
  };
  const api = new AdminApi({
    baseUrl: "http://backend.test/api/v1",
    getToken: () => "t",
    fetchImpl,
  });
  render(<FleetOccupancy api={api} />);
  return calls;
}

const flush = () => act(async () => {});

async function selectB05() {
  await flush();
  fireEvent.click(screen.getByRole("button", { name: "Monitor route of BUS B05" }));
  await flush();
  await flush();
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  mapProps.current = null;
});
afterEach(() => vi.useRealTimers());

describe("Admin route deviation (backend Feature 10, displayed as given)", () => {
  it("shows each bus's route status and distance in the fleet table", async () => {
    setup();
    await flush();
    const table = screen.getByRole("region", { name: "Fleet occupancy" });
    expect(within(table).getByRole("row", { name: "Bus B05" })).toHaveTextContent(
      "Major deviation312 m off route",
    );
    expect(within(table).getByRole("row", { name: "Bus B06" })).toHaveTextContent(
      "Minor deviation93 m off route",
    );
    const normal = within(table).getByRole("row", { name: "Bus B07" });
    expect(normal).toHaveTextContent("Normal");
    expect(normal).not.toHaveTextContent("off route");
  });

  it("shows the major alert from the backend", async () => {
    setup();
    await flush();
    const alerts = screen.getByRole("region", { name: "Active alerts" });
    expect(alerts).toHaveTextContent("BUS B05 is 312 m off its planned route.");
  });

  it("selecting a bus shows status, distance, timestamp and a map of backend data", async () => {
    const calls = setup();
    await selectB05();
    const monitor = screen.getByRole("region", { name: "Route monitor" });
    expect(within(monitor).getByRole("status")).toHaveTextContent(
      "Route status: Major deviation · 312 m from planned route",
    );
    expect(within(monitor).getByRole("alert")).toHaveTextContent(
      "BUS B05 is 312 m off its planned route.",
    );
    expect(monitor).toHaveTextContent("Trip T-B05");
    expect(calls.map((c) => c.key)).toContain("GET /api/v1/buses/B05/route-status");
    await screen.findByTestId("route-map");
    expect(mapProps.current).toMatchObject({
      route: ROUTE, // the backend's planned route
      bus: { lat: 12.915, lon: 80.214 }, // the backend's tracked position
      nearest: { lat: 12.912, lon: 80.212 },
      status: "MAJOR_DEVIATION",
    });
  });

  it("demo controls call the backend simulator for the selected bus", async () => {
    const calls = setup(
      routeStatus({ route_status: "NORMAL", deviation_distance_m: 4, message: null }),
    );
    await selectB05();
    const group = screen.getByRole("group", { name: "Route deviation demo" });
    for (const [label, mode] of [
      ["Simulate Minor Deviation", "minor"],
      ["Simulate Major Deviation", "major"],
      ["Normal", "normal"],
    ]) {
      fireEvent.click(within(group).getByRole("button", { name: label! }));
      await flush();
      const last = calls.filter((c) => c.key === "POST /api/v1/sim/route-deviation").at(-1);
      expect(last?.body).toEqual({ mode, bus_id: "B05" });
    }
  });

  it("never classifies or measures in the browser", async () => {
    // inconsistent on purpose: a big distance the backend still calls NORMAL
    setup(routeStatus({ route_status: "NORMAL", deviation_distance_m: 999, message: null }));
    await selectB05();
    const monitor = screen.getByRole("region", { name: "Route monitor" });
    expect(within(monitor).getByRole("status")).toHaveTextContent("Route status: Normal · 999 m");
    expect(within(monitor).queryByRole("alert")).not.toBeInTheDocument();
  });
});
