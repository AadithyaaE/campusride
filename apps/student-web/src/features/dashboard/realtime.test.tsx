import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../App";
import { ApiClient } from "../../api/client";
import { DERIVED_THROTTLE_MS, FALLBACK_POLL_MS } from "../../data/liveFleet";
import type { MapViewProps } from "../../map/MapView";
import { SessionStore } from "../../session/sessionStore";
import { FakeWebSocket } from "../../test/fakeSocket";
import * as fx from "../../test/fixtures";
import { fakeBackend, json, MemoryStorage } from "../../test/helpers";

const mapProps: { current: MapViewProps | null } = { current: null };
vi.mock("../../map/MapView", () => ({
  default: (props: MapViewProps) => {
    mapProps.current = props;
    return <div data-testid="map" />;
  },
}));

const wait = (ms: number) => act(() => new Promise((r) => setTimeout(r, ms)));
const settle = async () => {
  for (let i = 0; i < 4; i++) await wait(0);
};

async function connectedApp(overrides: Parameters<typeof fakeBackend>[0] = {}) {
  const store = new SessionStore(new MemoryStorage());
  store.set({ token: "mock.saved", expiresAt: "2099-01-01T00:00:00Z", userId: fx.me.id });
  const backend = fakeBackend(overrides);
  const api = new ApiClient({
    baseUrl: "http://backend.test/api/v1",
    getToken: () => store.get()?.token ?? null,
    fetchImpl: backend.fetchImpl,
  });
  render(<App api={api} store={store} />);
  await screen.findByRole("region", { name: "My bus live" }); // REST state first
  const sock = FakeWebSocket.last;
  await act(async () => sock.accept({ role: "student", heartbeat_s: 20 }));
  await settle();
  const count = (key: string) => backend.calls.filter((c) => c === key).length;
  return { backend, sock, count };
}

const push = async (sock: FakeWebSocket, type: string, data: unknown, over = {}) => {
  await act(async () => {
    sock.emit(type, data, over);
  });
  await settle();
};

const marker = (id: string) => mapProps.current?.buses.find((b) => b.id === id);
const feed = () => screen.getAllByRole("status", { name: "Live updates" })[0]!;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  mapProps.current = null;
  window.history.replaceState(null, "", "/");
});
afterEach(() => vi.useRealTimers());

describe("Student real-time (Feature 14)", () => {
  it("loads REST first, then connects, authenticates and re-syncs once", async () => {
    const { sock, count } = await connectedApp();
    expect(sock.url).toBe("ws://backend.test/api/v1/ws");
    expect(sock.sent[0]).toEqual({ type: "auth", token: "mock.saved" });
    expect(feed()).toHaveTextContent("Live · real-time updates");
    expect(count("GET /api/v1/buses")).toBe(2); // initial load + re-sync after connecting
    await act(async () => {
      vi.advanceTimersByTime(FALLBACK_POLL_MS * 3); // live: no fast polling
    });
    await settle();
    expect(count("GET /api/v1/buses")).toBe(2);
  });

  it("moves a bus on the map from a pushed GET /buses item (no extra fetch)", async () => {
    const { sock, count } = await connectedApp();
    const moved = {
      ...fx.buses[1]!,
      live: fx.live("T2", 6000, { last_updated: "2030-01-07T02:00:00Z" }),
    };
    await push(sock, "bus.state.updated", { bus: moved });
    expect(marker("BX8")?.lnglat).toEqual(moved.live.location.coordinates);
    expect(count("GET /api/v1/buses")).toBe(2);
  });

  it("ignores duplicate, stale and out-of-order bus updates", async () => {
    const { sock } = await connectedApp();
    const newer = {
      ...fx.buses[1]!,
      live: fx.live("T2", 6000, { last_updated: "2030-01-07T02:00:00Z" }),
    };
    const env = await act(async () => sock.emit("bus.state.updated", { bus: newer }));
    await settle();
    const older = {
      ...fx.buses[1]!,
      live: fx.live("T2", 100, { last_updated: "2030-01-07T01:00:00Z" }),
    };
    await push(sock, "bus.state.updated", { bus: older });
    const other = {
      ...fx.buses[1]!,
      live: fx.live("T2", 9000, { last_updated: "2030-01-07T03:00:00Z" }),
    };
    await push(sock, "bus.state.updated", { bus: other }, { id: env.id }); // duplicate id
    await push(sock, "bus.state.updated", { bus: other }, { seq: env.seq }); // stale seq
    expect(marker("BX8")?.lnglat).toEqual(newer.live.location.coordinates);
  });

  it("re-fetches the student's backend answers once after relevant ETA/occupancy/trip events", async () => {
    const { sock, count } = await connectedApp();
    const before = count("GET /api/v1/students/me/arrivals");
    await push(sock, "eta.updated", { bus_id: "BX7", eta_minutes: 4 });
    await push(sock, "occupancy.updated", { bus_id: "BX7", passengers: 44, capacity: 50 });
    await push(sock, "trip.started", { trip_id: "T9", bus_id: "BX9" });
    await wait(DERIVED_THROTTLE_MS + 100);
    expect(count("GET /api/v1/students/me/arrivals")).toBe(before + 1); // throttled: once
    expect(count("GET /api/v1/students/me/bus-options")).toBe(before + 1);
    expect(count("GET /api/v1/students/me/commute-decision")).toBe(before + 1);
    expect(count("GET /api/v1/students/me/recovery-options")).toBe(before + 1);
    // a bus unrelated to this student's stop changes nothing
    await push(sock, "eta.updated", { bus_id: "B-OTHER", eta_minutes: 2 });
    await wait(DERIVED_THROTTLE_MS + 100);
    expect(count("GET /api/v1/students/me/arrivals")).toBe(before + 1);
  });

  it("shows a route deviation pushed by the backend (via its re-fetched arrivals)", async () => {
    let deviated = false;
    const { sock } = await connectedApp({
      "GET /api/v1/students/me/arrivals": () =>
        json(
          deviated
            ? {
                ...fx.myArrivals,
                my_bus: {
                  ...fx.myArrivals.my_bus!,
                  route_status: "MAJOR_DEVIATION",
                  deviation_distance_m: 305,
                },
              }
            : fx.myArrivals,
        ),
    });
    deviated = true;
    await push(sock, "route.deviation", {
      bus_id: "BX7",
      route_status: "MAJOR_DEVIATION",
      previous_status: "NORMAL",
      deviation_distance_m: 305,
    });
    await wait(DERIVED_THROTTLE_MS + 100);
    const card = screen.getByRole("region", { name: "My bus live" });
    expect(card).toHaveTextContent("Major deviation · 305 m off route");
  });

  it("receives the student's own alerts and read state in real time", async () => {
    const { sock } = await connectedApp();
    const a = fx.alert("BUS_APPROACHING", "Bus BX7 reaches your stop in 2 minutes.", {
      alert_id: "A-LIVE",
      timestamp: "2030-01-07T02:00:00Z",
    });
    await push(sock, "alert.created", a);
    const panel = screen.getByRole("region", { name: "Notifications" });
    expect(panel).toHaveTextContent("Bus BX7 reaches your stop in 2 minutes.");
    expect(within(panel).getByLabelText("1 unread")).toBeInTheDocument();
    await push(sock, "alert.read", { alert_id: "A-LIVE", read: true });
    expect(within(panel).queryByLabelText("1 unread")).not.toBeInTheDocument();
  });

  it("falls back to 10 s polling when disconnected, then reconnects and re-syncs", async () => {
    const { sock, count } = await connectedApp();
    await act(async () => sock.drop());
    await settle();
    expect(feed()).toHaveTextContent("Live updates reconnecting · checking every 10 s");
    const n = count("GET /api/v1/buses");
    await act(async () => {
      vi.advanceTimersByTime(FALLBACK_POLL_MS);
    });
    await settle();
    expect(count("GET /api/v1/buses")).toBe(n + 1); // fallback poll
    await wait(1_100); // first reconnect after 1 s
    const again = FakeWebSocket.last;
    expect(again).not.toBe(sock);
    await act(async () => again.accept({ role: "student", heartbeat_s: 20 }));
    await settle();
    expect(again.sent[0]).toEqual({ type: "auth", token: "mock.saved" });
    expect(count("GET /api/v1/buses")).toBe(n + 2); // authoritative re-sync
    expect(feed()).toHaveTextContent("Live · real-time updates");
  });

  it("re-fetches everything after a simulator reset and answers heartbeats", async () => {
    const { sock, count } = await connectedApp();
    await push(sock, "ping", {});
    expect(sock.sent.at(-1)).toEqual({ type: "pong" });
    const n = count("GET /api/v1/sim/status");
    await push(sock, "sim.reset", {});
    expect(count("GET /api/v1/sim/status")).toBe(n + 1);
  });
});
