import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApi } from "../api/client";
import { FALLBACK_POLL_MS } from "../polling";
import { fakeBackend, fleet, fleetBus, type Handler, json } from "../test/backend";
import { ControlRoom } from "./ControlRoom";
import type { FleetMapProps } from "./FleetMap";

const mapProps: { current: FleetMapProps | null } = { current: null };
vi.mock("./FleetMap", () => ({
  default: (p: FleetMapProps) => {
    mapProps.current = p;
    return (
      <div data-testid="fleet-map">
        {p.buses.map((b) => (
          <button key={b.bus_id} type="button" onClick={() => p.onSelectBus(b.bus_id)}>
            map marker {b.bus_id}
          </button>
        ))}
      </div>
    );
  },
}));
vi.mock("../RouteMap", () => ({ default: () => <div data-testid="route-map" /> }));

const settle = async () => {
  for (let i = 0; i < 4; i++) {
    await act(() => new Promise((r) => setTimeout(r, 0)));
  }
};

function setup(override?: Handler) {
  const b = fakeBackend(override);
  const api = new AdminApi({
    baseUrl: "http://b.test/api/v1",
    getToken: () => "t",
    fetchImpl: b.fetchImpl,
  });
  render(<ControlRoom api={api} />);
  return b;
}

async function tick(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
  await settle();
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  mapProps.current = null;
});
afterEach(() => vi.useRealTimers());

describe("Control room — KPIs and alerts", () => {
  it("shows the four KPI cards exactly as the backend counted", async () => {
    setup();
    await settle();
    const kpis = screen.getByRole("region", { name: "Key figures" });
    expect(within(kpis).getByRole("group", { name: "Total buses" })).toHaveTextContent("12");
    expect(within(kpis).getByRole("group", { name: "Total buses" })).toHaveTextContent("5 on trip");
    expect(within(kpis).getByRole("group", { name: "Active trips" })).toHaveTextContent("5");
    expect(within(kpis).getByRole("group", { name: "Students" })).toHaveTextContent("300");
    expect(within(kpis).getByRole("group", { name: "Students" })).toHaveTextContent("296 assigned");
    expect(within(kpis).getByRole("group", { name: "Passengers today" })).toHaveTextContent("187");
    expect(within(kpis).getByRole("group", { name: "Passengers today" })).toHaveTextContent(
      "4 QR boardings",
    );
    expect(within(kpis).getByLabelText("Exceptions")).toHaveTextContent("1 delayed");
  });

  it("summarises active alerts by severity near the top and opens the bus", async () => {
    setup();
    await settle();
    const summary = screen.getByRole("region", { name: "Alert summary" });
    expect(summary).toHaveTextContent("3 Active alerts");
    const rows = within(summary).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("CriticalBus 05 is 303 m off route");
    expect(rows[1]).toHaveTextContent("Warning");
    fireEvent.click(within(summary).getByRole("button", { name: "Bus 05 is 303 m off route" }));
    expect(screen.getByRole("region", { name: "Bus detail" })).toHaveTextContent("BUS 05");
  });

  it("lists alerts with bus, route, time and read state, and marks them read", async () => {
    const b = setup();
    await settle();
    const panel = screen.getByRole("region", { name: "Active alerts" });
    expect(within(panel).getByLabelText("3 unread")).toBeInTheDocument();
    const first = within(panel).getAllByRole("listitem")[0]!;
    expect(first).toHaveTextContent("ROUTE DEVIATION");
    expect(first).toHaveTextContent("Critical");
    expect(first).toHaveTextContent("Active");
    expect(first).toHaveTextContent("Bus B05 · R3");
    expect(first).toHaveTextContent("Unread");
    fireEvent.click(
      within(panel).getByRole("button", { name: "Mark ROUTE DEVIATION for B05 read" }),
    );
    await settle();
    expect(b.calls.map((c) => c.key)).toContain(
      "PATCH /api/v1/alerts/ALT-ROUTE_DEVIATION-ADMIN-B05-T1-1/read",
    );
    expect(within(panel).getByLabelText("2 unread")).toBeInTheDocument();
  });

  it("shows resolved alerts from the backend on request", async () => {
    const b = setup();
    await settle();
    const panel = screen.getByRole("region", { name: "Active alerts" });
    fireEvent.click(within(panel).getByRole("tab", { name: "Resolved" }));
    await settle();
    expect(b.calls.map((c) => c.key)).toContain("GET /api/v1/alerts?active=false");
    const resolved = within(panel).getByRole("list", { name: "Resolved alerts" });
    expect(resolved).toHaveTextContent("Bus 02 was 6 min late");
    expect(resolved).toHaveTextContent("Resolved");
  });
});

describe("Control room — live fleet", () => {
  it("renders the fleet table with backend speed, ETA, occupancy and route status", async () => {
    setup();
    await settle();
    const table = screen.getByRole("table", { name: "Fleet table" });
    const b07 = within(table).getByRole("row", { name: "Bus B07" });
    expect(b07).toHaveTextContent("07");
    expect(b07).toHaveTextContent("R4");
    expect(b07).toHaveTextContent("Active");
    expect(b07).toHaveTextContent("32 km/h");
    expect(b07).toHaveTextContent("6 min");
    expect(b07).toHaveTextContent("38/50");
    expect(b07).toHaveTextContent("Normal");
    expect(b07).toHaveTextContent("Library Gate");
    const b15 = within(table).getByRole("row", { name: "Bus B15" });
    expect(b15).toHaveTextContent("Delayed");
    expect(b15).toHaveTextContent("+8 min");
    expect(b15).toHaveTextContent("41/50");
    expect(within(table).getByRole("row", { name: "Bus B05" })).toHaveTextContent(
      "Major deviation303 m off route",
    );
    expect(within(table).getByRole("row", { name: "Bus B09" })).toHaveTextContent("Idle");
  });

  it("displays backend numbers as given — no local maths", async () => {
    setup((key) =>
      key === "GET /api/v1/admin/fleet"
        ? json(
            fleet([
              fleetBus("B05", { occupancy: 10, occupancy_percentage: 91, available_seats: 3 }),
            ]),
          )
        : undefined,
    );
    await settle();
    const row = screen.getByRole("row", { name: "Bus B05" });
    expect(row).toHaveTextContent("10/50");
    expect(row).toHaveTextContent("91%");
  });

  it("filters by route, bus and status on the backend fleet rows (table + map)", async () => {
    setup();
    await settle();
    const table = () => screen.getByRole("table", { name: "Fleet table" });
    fireEvent.change(screen.getByLabelText("Route filter"), { target: { value: "R3" } });
    expect(within(table()).getAllByRole("row")).toHaveLength(3); // header + B05 + B06
    expect(mapProps.current?.buses.map((b) => b.bus_id)).toEqual(["B05", "B06"]);
    expect(mapProps.current?.focusRouteId).toBe("R3");
    fireEvent.change(screen.getByLabelText("Status filter"), { target: { value: "deviated" } });
    expect(within(table()).getByRole("row", { name: "Bus B05" })).toBeInTheDocument();
    expect(within(table()).queryByRole("row", { name: "Bus B06" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    fireEvent.change(screen.getByLabelText("Bus filter"), { target: { value: "B12" } });
    expect(within(table()).getAllByRole("row")).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Status filter"), { target: { value: "delayed" } });
    expect(screen.getByText("No buses match the current filters.")).toBeInTheDocument();
    // options come from the backend response
    expect(within(screen.getByLabelText("Route filter")).getAllByRole("option")).toHaveLength(6);
  });

  it("draws routes and buses on the live map; clicking a marker opens the bus", async () => {
    setup();
    await settle();
    await screen.findByTestId("fleet-map");
    expect(mapProps.current?.buses).toHaveLength(6);
    expect(mapProps.current?.routes.map((r) => r.id)).toEqual(["R1", "R2", "R3"]);
    expect(mapProps.current?.routes[0]?.coords).toEqual([
      [80.1, 12.9],
      [80.12, 12.92],
    ]);
    fireEvent.click(screen.getByRole("button", { name: "map marker B15" }));
    expect(mapProps.current?.selectedBusId).toBe("B15");
    const detail = screen.getByRole("region", { name: "Bus detail" });
    expect(detail).toHaveTextContent("BUS 15");
  });

  it("lists active buses from the same fleet rows", async () => {
    setup();
    await settle();
    const panel = screen.getByRole("region", { name: "Active buses" });
    const cards = within(panel).getAllByRole("listitem");
    expect(cards).toHaveLength(5); // idle B09 excluded
    const b07 = within(panel).getByRole("button", { name: "Active BUS B07" });
    expect(b07).toHaveTextContent("BUS 07");
    expect(b07).toHaveTextContent("32 km/h");
    expect(b07).toHaveTextContent("Next: Library Gate");
    expect(b07).toHaveTextContent("ETA: 6 min");
    expect(b07).toHaveTextContent("38/50");
  });

  it("shows occupancy with the backend crowding band and seats", async () => {
    setup();
    await settle();
    const panel = screen.getByRole("region", { name: "Occupancy" });
    const rows = within(panel).getAllByRole("row");
    expect(rows[1]).toHaveAccessibleName("Occupancy BUS B15"); // most occupied first
    expect(rows[1]).toHaveTextContent("41/50");
    expect(rows[1]).toHaveTextContent("82%");
    expect(rows[1]).toHaveTextContent("9");
    expect(rows[1]).toHaveTextContent("High");
    expect(within(panel).getByRole("row", { name: "Occupancy BUS B12" })).toHaveTextContent("Low");
  });

  it("shows route deviation counts and deviated buses; selecting focuses the map", async () => {
    setup();
    await settle();
    const panel = screen.getByRole("region", { name: "Route deviations" });
    const tally = within(panel).getByLabelText("Route status counts");
    expect(tally).toHaveTextContent("Normal3");
    expect(tally).toHaveTextContent("Minor deviation1");
    expect(tally).toHaveTextContent("Major deviation1");
    const items = within(panel).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Bus 05");
    expect(items[0]).toHaveTextContent("303 m");
    expect(items[0]).toHaveTextContent("Critical alert active");
    expect(items[1]).toHaveTextContent("93 m");
    fireEvent.click(within(panel).getByRole("button", { name: "Focus BUS B05 on map" }));
    expect(mapProps.current?.selectedBusId).toBe("B05");
  });

  it("shows delays from the backend rule, or 'No active delays'", async () => {
    setup();
    await settle();
    const panel = screen.getByRole("region", { name: "Delays" });
    expect(within(panel).getAllByRole("listitem")).toHaveLength(1);
    expect(panel).toHaveTextContent("Bus 15");
    expect(panel).toHaveTextContent("+8 min");
    expect(panel).toHaveTextContent("Next: Library Gate");
  });

  it("empty states: no delays, no deviations, no active buses", async () => {
    setup((key) =>
      key === "GET /api/v1/admin/fleet"
        ? json(fleet([fleetBus("B01", { operational_status: "waiting", bus_status: "at_depot" })]))
        : undefined,
    );
    await settle();
    expect(screen.getByRole("region", { name: "Delays" })).toHaveTextContent("No active delays");
    expect(screen.getByRole("region", { name: "Route deviations" })).toHaveTextContent(
      "All tracked buses are on their planned routes.",
    );
    expect(screen.getByRole("region", { name: "Active buses" })).toHaveTextContent(
      "No bus is on a running trip.",
    );
  });
});

describe("Control room — details", () => {
  it("bus detail shows every backend field plus its alerts", async () => {
    setup();
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Open BUS B15" }));
    await settle();
    const d = screen.getByRole("region", { name: "Bus detail" });
    for (const text of [
      "TN 00 CR B15",
      "R2 · Velachery",
      "R1 — To Campus",
      "Driver B15 (D15)",
      "T-B15",
      "18 km/h",
      "Tambaram Station",
      "Library Gate",
      "15 min",
      "high confidence",
      "41/50 · 82% · 9 seats free",
      "+8 min",
      "Normal",
      "4 m from planned route",
      "LIVE",
      "3s ago",
    ]) {
      expect(d).toHaveTextContent(text);
    }
    expect(within(d).getByLabelText("Bus alerts")).toHaveTextContent("Bus 15 is 8 min delayed");
    fireEvent.click(within(d).getByRole("button", { name: "Close bus detail" }));
    expect(screen.queryByRole("region", { name: "Bus detail" })).not.toBeInTheDocument();
  });

  it("bus detail reuses the trip boarding view", async () => {
    setup((key) =>
      key === "GET /api/v1/admin/fleet"
        ? json(fleet([fleetBus("B05", { trip_id: "T-B05" })]))
        : undefined,
    );
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Open BUS B05" }));
    fireEvent.click(screen.getByRole("button", { name: "Boarding for trip T-B05" }));
    await settle();
    const panel = screen.getByRole("region", { name: "Trip boarding" });
    expect(panel).toHaveTextContent("1 QR boarding on B05 (R3)");
    expect(within(panel).getByRole("list", { name: "Boarding events" })).toHaveTextContent(
      "U-S0001",
    );
  });

  it("route management lists routes read-only; selecting one opens route detail", async () => {
    setup();
    await settle();
    const panel = screen.getByRole("region", { name: "Route management" });
    expect(panel).toHaveTextContent("Read-only");
    const r3 = within(panel).getByRole("row", { name: "Route R3" });
    expect(r3).toHaveTextContent("18.4 km");
    expect(r3).toHaveTextContent("2/2");
    expect(r3).toHaveTextContent("2 deviated");
    expect(within(panel).getByRole("row", { name: "Route R2" })).toHaveTextContent("1 delayed");
    expect(
      within(panel).queryByRole("button", { name: /edit|save|delete/i }),
    ).not.toBeInTheDocument();

    fireEvent.click(within(panel).getByRole("button", { name: "Open route R3" }));
    await settle();
    const d = screen.getByRole("region", { name: "Route detail" });
    expect(d).toHaveTextContent("Thiruvanmiyur – OMR");
    expect(d).toHaveTextContent("Avg occupancy62%");
    const stops = within(
      within(d).getByRole("list", { name: "Stops R3 — To Campus" }),
    ).getAllByRole("listitem");
    expect(stops.map((li) => li.textContent)).toEqual([
      expect.stringContaining("Tambaram Station"),
      expect.stringContaining("Library Gate"),
      expect.stringContaining("Campus"),
    ]);
    fireEvent.click(within(d).getByRole("tab", { name: /From campus/ }));
    const back = within(d).getByRole("list", { name: "Stops R3 — From Campus" });
    expect(within(back).getAllByRole("listitem")[0]).toHaveTextContent("Campus");
    expect(d).toHaveTextContent("Bus 05");
    expect(d).toHaveTextContent("303 m");
    expect(mapProps.current?.focusRouteId).toBe("R3");
  });

  it("schedule lists today's trips read-only with bus, driver and status", async () => {
    setup();
    await settle();
    const panel = screen.getByRole("region", { name: "Schedule management" });
    expect(panel).toHaveTextContent("Read-only");
    const t = within(panel).getByRole("row", { name: "Trip T-20261005-R1-0715" });
    expect(t).toHaveTextContent("R1 — To Campus");
    expect(t).toHaveTextContent("07:15"); // campus time
    expect(t).toHaveTextContent("08:07");
    expect(t).toHaveTextContent("Ravi Shankar");
    expect(t).toHaveTextContent("Active");
    expect(t).toHaveTextContent("+2 min");
    expect(within(panel).getByRole("row", { name: "Trip T-20261005-R2-0730" })).toHaveTextContent(
      "Scheduled",
    );
    expect(within(panel).queryByRole("button", { name: /edit|save|add/i })).not.toBeInTheDocument();
  });

  it("analytics separates live backend data from labelled synthetic demo data", async () => {
    setup();
    await settle();
    const live = screen.getByLabelText("Live analytics");
    expect(within(live).getByRole("figure", { name: "Passengers per route" })).toHaveTextContent(
      "R171",
    );
    expect(within(live).getByRole("figure", { name: "Occupancy by bus" })).toHaveTextContent(
      "41/50 · 82%",
    );
    expect(within(live).getByRole("figure", { name: "Trips today" })).toHaveTextContent("Total24");
    expect(within(live).getByRole("figure", { name: "Average delay" })).toHaveTextContent(
      "+2.4 min",
    );
    expect(
      within(live).getByRole("figure", { name: "QR boardings by time (today)" }),
    ).toHaveTextContent("No QR boardings yet today.");
    expect(live).not.toHaveTextContent("Synthetic demo data");
    const syn = screen.getByLabelText("Synthetic analytics");
    expect(syn).toHaveTextContent("Synthetic demo data");
    expect(
      within(syn).getByRole("figure", { name: "Peak boarding time — 07:00" }),
    ).toBeInTheDocument();
    expect(
      within(syn).getByRole("figure", { name: "Passengers per day (last 7 days)" }),
    ).toHaveTextContent("455");
  });
});

describe("Control room — loading, errors and polling", () => {
  it("shows loading states before the first response", () => {
    setup();
    expect(screen.getAllByText("Loading live fleet…").length).toBeGreaterThan(0);
    expect(screen.getByText("Loading analytics…")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Live status" })).toHaveTextContent("Connecting…");
  });

  it("shows a clear error when the backend is unreachable", async () => {
    setup(() => {
      throw new TypeError("network down");
    });
    await settle();
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent(
      "The CampusRide backend is not reachable.",
    );
    expect(screen.getByRole("status", { name: "Live status" })).toHaveTextContent(
      "Backend unreachable",
    );
    expect(screen.getByText("Fleet data is unavailable.")).toBeInTheDocument();
  });

  it("keeps the last fleet data when a later poll fails", async () => {
    let fail = false;
    setup((key) => {
      if (fail && key === "GET /api/v1/admin/fleet")
        return json({ error: { code: "x", message: "boom" } }, 500);
      return undefined;
    });
    await settle();
    fail = true;
    await tick(FALLBACK_POLL_MS);
    expect(screen.getByRole("row", { name: "Bus B07" })).toBeInTheDocument();
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent("showing the last data received");
  });

  it("without a live socket: polls the fleet once per 10 s for all panels, analytics less often", async () => {
    let n = 0;
    const b = setup((key) => {
      if (key === "GET /api/v1/admin/fleet") {
        n += 1;
        return json(fleet([fleetBus("B07", { occupancy: 38 + n - 1, speed_kmh: 30 + n })]));
      }
      return undefined;
    });
    await settle();
    expect(b.count("GET /api/v1/admin/fleet")).toBe(1); // one request feeds table, map, panels
    expect(screen.getByRole("row", { name: "Bus B07" })).toHaveTextContent("38/50");
    await tick(FALLBACK_POLL_MS); // t = 10 s (WebSocket never came up → fallback polling)
    expect(b.count("GET /api/v1/admin/fleet")).toBe(2);
    expect(screen.getByRole("row", { name: "Bus B07" })).toHaveTextContent("39/50");
    expect(screen.getByRole("button", { name: "Active BUS B07" })).toHaveTextContent("32 km/h");
    expect(b.count("GET /api/v1/admin/overview")).toBe(2);
    expect(b.count("GET /api/v1/alerts?active=true")).toBe(2);
    expect(b.count("GET /api/v1/admin/analytics")).toBe(1);
    await tick(5_000); // t = 15 s
    expect(b.count("GET /api/v1/admin/schedule")).toBe(2);
    expect(b.count("GET /api/v1/admin/analytics")).toBe(1);
    await tick(5_000); // t = 20 s
    expect(b.count("GET /api/v1/admin/analytics")).toBe(2);
    expect(b.count("GET /api/v1/admin/fleet")).toBe(3);
    // route geometry is reference data: fetched once per route
    expect(b.count("GET /api/v1/routes/R1")).toBe(1);
  });

  it("KPI overview errors are shown without hiding the rest", async () => {
    setup((key) =>
      key === "GET /api/v1/admin/overview"
        ? json({ error: { code: "forbidden", message: "nope" } }, 403)
        : undefined,
    );
    await settle();
    expect(screen.getByRole("region", { name: "Key figures" })).toHaveTextContent("Overview: nope");
    expect(screen.getByRole("row", { name: "Bus B07" })).toBeInTheDocument();
  });
});
