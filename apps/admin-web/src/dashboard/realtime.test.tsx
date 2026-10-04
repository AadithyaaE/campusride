import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApi } from "../api/client";
import { FALLBACK_POLL_MS } from "../polling";
import { alert, fakeBackend, fleetBus, OVERVIEW } from "../test/backend";
import { FakeWebSocket } from "../test/fakeSocket";
import { ControlRoom } from "./ControlRoom";
import type { FleetMapProps } from "./FleetMap";

const mapProps: { current: FleetMapProps | null } = { current: null };
vi.mock("./FleetMap", () => ({
  default: (p: FleetMapProps) => {
    mapProps.current = p;
    return <div data-testid="fleet-map" />;
  },
}));
vi.mock("../RouteMap", () => ({ default: () => <div data-testid="route-map" /> }));

const wait = (ms: number) => act(() => new Promise((r) => setTimeout(r, ms)));
const settle = async () => {
  for (let i = 0; i < 4; i++) await wait(0);
};

async function connected() {
  const b = fakeBackend();
  const api = new AdminApi({
    baseUrl: "http://b.test/api/v1",
    getToken: () => "mock.admin",
    fetchImpl: b.fetchImpl,
  });
  render(<ControlRoom api={api} />);
  await settle(); // initial REST state first
  const sock = FakeWebSocket.last;
  await act(async () => sock.accept());
  await settle();
  return { b, sock };
}

const push = async (sock: FakeWebSocket, type: string, data: unknown, over = {}) => {
  await act(async () => {
    sock.emit(type, data, over);
  });
  await settle();
};

const row = (id: string) => screen.getByRole("row", { name: `Bus ${id}` });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  mapProps.current = null;
});
afterEach(() => vi.useRealTimers());

describe("Admin real-time (Feature 14)", () => {
  it("loads REST first, then authenticates the socket and goes live", async () => {
    const { b, sock } = await connected();
    expect(sock.url).toBe("ws://b.test/api/v1/ws");
    expect(sock.sent[0]).toEqual({ type: "auth", token: "mock.admin" });
    expect(screen.getByRole("status", { name: "Live status" })).toHaveTextContent(
      "Live · real-time",
    );
    // initial load + one re-sync right after connecting (closes the load/connect race)
    expect(b.count("GET /api/v1/admin/fleet")).toBe(2);
    // while live there is no fast polling: nothing more within the old fallback window
    await act(async () => {
      vi.advanceTimersByTime(FALLBACK_POLL_MS * 2);
    });
    await settle();
    expect(b.count("GET /api/v1/admin/fleet")).toBe(2);
  });

  it("moves a bus on the map and in the table from a pushed fleet row", async () => {
    const { b, sock } = await connected();
    const moved = fleetBus("B07", {
      route_id: "R4",
      location: { lat: 13.0, lon: 80.25 },
      speed_kmh: 41,
      last_updated: "2026-10-05T02:10:05Z",
    });
    await push(sock, "fleet.bus.updated", { bus: moved });
    expect(row("B07")).toHaveTextContent("41 km/h");
    const onMap = mapProps.current?.buses.find((x) => x.bus_id === "B07");
    expect(onMap?.location).toEqual({ lat: 13.0, lon: 80.25 });
    expect(b.count("GET /api/v1/admin/fleet")).toBe(2); // the push, not another fetch
  });

  it("ignores late, duplicate and out-of-order events", async () => {
    const { sock } = await connected();
    const newer = fleetBus("B07", { speed_kmh: 50, last_updated: "2026-10-05T02:11:00Z" });
    const env = await act(async () => sock.emit("fleet.bus.updated", { bus: newer }));
    await settle();
    expect(row("B07")).toHaveTextContent("50 km/h");
    const older = fleetBus("B07", { speed_kmh: 5, last_updated: "2026-10-05T02:09:00Z" });
    await push(sock, "fleet.bus.updated", { bus: older }); // older backend fix
    await push(sock, "fleet.bus.updated", { bus: { ...newer, speed_kmh: 7 } }, { id: env.id }); // dup id
    await push(sock, "fleet.bus.updated", { bus: { ...newer, speed_kmh: 9 } }, { seq: env.seq }); // stale seq
    expect(row("B07")).toHaveTextContent("50 km/h");
  });

  it("trip start and completion update the bus immediately and refresh the schedule", async () => {
    const { b, sock } = await connected();
    const before = b.count("GET /api/v1/admin/schedule");
    await push(sock, "trip.started", { trip_id: "T-B09", bus_id: "B09", route_id: "R5" });
    await push(sock, "fleet.bus.updated", {
      bus: fleetBus("B09", { route_id: "R5", operational_status: "active", speed_kmh: 22 }),
    });
    expect(row("B09")).toHaveTextContent("Active");
    expect(
      within(screen.getByRole("region", { name: "Active buses" })).getAllByRole("listitem"),
    ).toHaveLength(6);
    await wait(600); // debounced re-fetch of schedule + routes
    expect(b.count("GET /api/v1/admin/schedule")).toBe(before + 1);
    await push(sock, "trip.completed", { trip_id: "T-B09", bus_id: "B09" });
    await push(sock, "fleet.bus.updated", {
      bus: fleetBus("B09", {
        route_id: "R5",
        operational_status: "completed",
        trip_status: "completed",
        last_updated: "2026-10-05T02:20:00Z",
      }),
    });
    expect(row("B09")).toHaveTextContent("Completed");
  });

  it("occupancy, delay and route deviation changes arrive as fleet rows", async () => {
    const { sock } = await connected();
    await push(sock, "fleet.bus.updated", {
      bus: fleetBus("B07", {
        route_id: "R4",
        occupancy: 45,
        available_seats: 5,
        occupancy_percentage: 90,
        crowding: "High",
        operational_status: "deviated",
        route_status: "MAJOR_DEVIATION",
        deviation_distance_m: 310,
        is_delayed: true,
        delay_s: 540,
        delay_min: 9,
        last_updated: "2026-10-05T02:12:00Z",
      }),
    });
    expect(row("B07")).toHaveTextContent("45/50");
    expect(screen.getByRole("row", { name: "Occupancy BUS B07" })).toHaveTextContent("90%");
    const dev = screen.getByRole("region", { name: "Route deviations" });
    expect(dev).toHaveTextContent("Bus 07");
    expect(dev).toHaveTextContent("310 m");
    expect(screen.getByRole("region", { name: "Delays" })).toHaveTextContent("+9 min");
  });

  it("applies pushed KPIs and alert events", async () => {
    const { sock } = await connected();
    await push(sock, "admin.overview.updated", {
      ...OVERVIEW,
      active_trips: 6,
      passengers_today: 201,
    });
    const kpis = screen.getByRole("region", { name: "Key figures" });
    expect(within(kpis).getByRole("group", { name: "Active trips" })).toHaveTextContent("6");
    expect(within(kpis).getByRole("group", { name: "Passengers today" })).toHaveTextContent("201");

    const fresh = alert("BUS_DELAYED", "Bus 12 is 7 min delayed", {
      alert_id: "A-NEW",
      bus_id: "B12",
      timestamp: "2026-10-05T02:15:00Z",
    });
    await push(sock, "alert.created", fresh);
    const summary = screen.getByRole("region", { name: "Alert summary" });
    expect(summary).toHaveTextContent("4 Active alerts");
    const panel = screen.getByRole("region", { name: "Active alerts" });
    expect(within(panel).getByLabelText("4 unread")).toBeInTheDocument();
    await push(sock, "alert.read", { alert_id: "A-NEW", read: true });
    expect(within(panel).getByLabelText("3 unread")).toBeInTheDocument();
    await push(sock, "alert.resolved", { ...fresh, active: false });
    expect(summary).toHaveTextContent("3 Active alerts");
    // a student's alert is never shown in the fleet view, even if pushed by mistake
    await push(
      sock,
      "alert.created",
      alert("MISSED_BUS", "You missed it", { recipient: "student", alert_id: "S" }),
    );
    expect(summary).toHaveTextContent("3 Active alerts");
  });

  it("falls back to 10 s polling when the socket drops, then reconnects and re-syncs", async () => {
    const { b, sock } = await connected();
    await act(async () => sock.drop());
    await settle();
    expect(screen.getByRole("status", { name: "Live status" })).toHaveTextContent(
      "Reconnecting… · polling every 10s",
    );
    const n = b.count("GET /api/v1/admin/fleet");
    await act(async () => {
      vi.advanceTimersByTime(FALLBACK_POLL_MS);
    });
    await settle();
    expect(b.count("GET /api/v1/admin/fleet")).toBe(n + 1); // fallback polling
    await wait(1_100); // backoff: first retry after 1 s
    expect(FakeWebSocket.instances).toHaveLength(2);
    const again = FakeWebSocket.last;
    expect(again.sent).toEqual([]); // not authenticated until the socket opens
    await act(async () => again.accept());
    await settle();
    expect(again.sent[0]).toEqual({ type: "auth", token: "mock.admin" });
    expect(screen.getByRole("status", { name: "Live status" })).toHaveTextContent(
      "Live · real-time",
    );
    expect(b.count("GET /api/v1/admin/fleet")).toBe(n + 2); // one authoritative re-sync
  });

  it("answers heartbeats and re-syncs everything after a simulator reset", async () => {
    const { b, sock } = await connected();
    await push(sock, "ping", {});
    expect(sock.sent.at(-1)).toEqual({ type: "pong" });
    const before = b.count("GET /api/v1/admin/overview");
    await push(sock, "sim.reset", { scenario: null });
    expect(b.count("GET /api/v1/admin/overview")).toBe(before + 1);
  });
});
