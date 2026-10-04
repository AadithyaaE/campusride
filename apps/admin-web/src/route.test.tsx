import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApi, type RouteStatusResponse } from "./api/client";
import { ControlRoom } from "./dashboard/ControlRoom";
import type { RouteMapProps } from "./RouteMap";
import { fakeBackend, json, routeStatus } from "./test/backend";

const mapProps: { current: RouteMapProps | null } = { current: null };
vi.mock("./RouteMap", () => ({
  default: (p: RouteMapProps) => {
    mapProps.current = p;
    return <div data-testid="route-map" />;
  },
}));
vi.mock("./dashboard/FleetMap", () => ({ default: () => <div data-testid="fleet-map" /> }));

const settle = async () => {
  for (let i = 0; i < 4; i++) await act(() => new Promise((r) => setTimeout(r, 0)));
};

function setup(rs: RouteStatusResponse = routeStatus()) {
  const b = fakeBackend((key) =>
    key === "GET /api/v1/buses/B05/route-status" ? json(rs) : undefined,
  );
  const api = new AdminApi({
    baseUrl: "http://backend.test/api/v1",
    getToken: () => "t",
    fetchImpl: b.fetchImpl,
  });
  render(<ControlRoom api={api} />);
  return b.calls;
}

async function selectB05() {
  await settle();
  fireEvent.click(screen.getByRole("button", { name: "Open BUS B05" }));
  await settle();
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  mapProps.current = null;
});
afterEach(() => vi.useRealTimers());

describe("Admin route deviation (backend Feature 10, displayed as given)", () => {
  it("shows each bus's route status and distance in the fleet table", async () => {
    setup();
    await settle();
    const table = screen.getByRole("table", { name: "Fleet table" });
    expect(within(table).getByRole("row", { name: "Bus B05" })).toHaveTextContent(
      "Major deviation303 m off route",
    );
    expect(within(table).getByRole("row", { name: "Bus B06" })).toHaveTextContent(
      "Minor deviation93 m off route",
    );
    const normal = within(table).getByRole("row", { name: "Bus B07" });
    expect(normal).toHaveTextContent("Normal");
    expect(normal).not.toHaveTextContent("off route");
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
      route: routeStatus().expected_route!.coordinates,
      bus: { lat: 12.915, lon: 80.214 },
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
      await settle();
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
