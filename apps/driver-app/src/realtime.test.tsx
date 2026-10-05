import { act, fireEvent, render, screen } from "@testing-library/react-native";

import { AppRoot } from "../App";
import {
  activeDash,
  dash,
  fakeBackend,
  json,
  PASSWORD_AUTH,
  type Handler,
} from "./test/fakeBackend";
import { FakeWebSocket } from "./test/fakeSocket";

const wait = (ms: number) => act(() => new Promise<void>((r) => setTimeout(r, ms)));

async function connected(overrides: Record<string, Handler> = {}) {
  const backend = fakeBackend(overrides);
  await render(<AppRoot fetchImpl={backend.fetchImpl} />);
  await screen.findByText(/Demo sign-in/); // options from GET /auth/config
  await fireEvent.press(screen.getByRole("button", { name: "SIGN IN" }));
  expect(await screen.findByText("Arun Kumar")).toBeTruthy(); // REST state first
  const sock = FakeWebSocket.last;
  await act(async () => sock.accept({ role: "driver", bus_id: "B07", heartbeat_s: 20 }));
  const count = (key: string) => backend.calls.filter((c) => c === key).length;
  return { backend, sock, count };
}

const push = (sock: FakeWebSocket, type: string, data: unknown) =>
  act(async () => {
    sock.emit(type, data);
  });

describe("Driver App real-time (Feature 14)", () => {
  it("loads REST first, then authenticates the socket as this driver", async () => {
    const { sock, count } = await connected();
    expect(sock.url).toBe("ws://localhost:8000/api/v1/ws");
    expect(sock.sent[0]).toEqual({ type: "auth", token: "mock.driver" });
    expect(await screen.findByLabelText("Connection: Connected")).toBeTruthy();
    expect(count("GET /api/v1/driver/me")).toBeGreaterThanOrEqual(2); // initial + re-sync
  });

  it("applies the backend's pushed /driver/me: trip status, speed, passengers, next stop, route status", async () => {
    const { sock } = await connected();
    await push(sock, "driver.state.updated", activeDash());
    expect(await screen.findByText("DRIVING")).toBeTruthy();
    await push(
      sock,
      "driver.state.updated",
      activeDash({
        next_stop: "Main Gate",
        live: {
          ...activeDash().live!,
          speed_kmh: 45,
          occupancy: 41,
          available_seats: 9,
          next_stop: "Main Gate",
          route_status: "MAJOR_DEVIATION",
          deviation_distance_m: 310,
        },
      }),
    );
    expect(screen.getByLabelText("SPEED: 45 km/h")).toBeTruthy();
    expect(screen.getByLabelText("PASSENGERS: 41 / 50 · 9 seats free")).toBeTruthy();
    expect(screen.getByLabelText("NEXT STOP: Main Gate")).toBeTruthy();
    expect(screen.getByLabelText("ROUTE STATUS: MAJOR DEVIATION")).toBeTruthy();
  });

  it("re-fetches on trip events (trip.completed → READY from the backend)", async () => {
    let active = true;
    const { sock, count } = await connected({
      "GET /api/v1/driver/me": () => json(active ? activeDash() : dash()),
    });
    expect(await screen.findByText("DRIVING")).toBeTruthy();
    const n = count("GET /api/v1/driver/me");
    active = false;
    await push(sock, "trip.completed", { trip_id: "T-20261005-R4-0715", bus_id: "B07" });
    expect(await screen.findByText("READY")).toBeTruthy();
    expect(count("GET /api/v1/driver/me")).toBe(n + 1);
  });

  it("reconnects after a drop and re-syncs over REST", async () => {
    const { sock, count } = await connected();
    await act(async () => sock.drop());
    expect(await screen.findByLabelText("Connection: Reconnecting…")).toBeTruthy();
    const n = count("GET /api/v1/driver/me");
    await wait(1_100); // first retry after 1 s
    const again = FakeWebSocket.last;
    expect(again).not.toBe(sock);
    await act(async () => again.accept({ role: "driver", bus_id: "B07", heartbeat_s: 20 }));
    expect(again.sent[0]).toEqual({ type: "auth", token: "mock.driver" });
    expect(await screen.findByLabelText("Connection: Connected")).toBeTruthy();
    expect(count("GET /api/v1/driver/me")).toBe(n + 1);
  });

  it("actions still go through REST while live", async () => {
    const { backend, sock } = await connected();
    await fireEvent.press(await screen.findByRole("button", { name: "START TRIP" }));
    expect(await screen.findByText("DRIVING")).toBeTruthy();
    expect(backend.calls).toContain("POST /api/v1/driver/trip/start");
    expect(sock.sent.filter((m) => m.type !== "auth" && m.type !== "pong")).toEqual([]); // receive-only
  });

  it("a refused socket session (4401) signs the driver out with a message", async () => {
    const { sock } = await connected();
    await act(async () => sock.drop(4401));
    expect(await screen.findByText("Your session has ended. Please sign in again.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "SIGN IN" })).toBeTruthy();
  });
});

describe("Driver sign-in modes (Feature 15)", () => {
  it("password mode: email + password, no development label", async () => {
    const backend = fakeBackend({ "GET /api/v1/auth/config": () => json(PASSWORD_AUTH) });
    await render(<AppRoot fetchImpl={backend.fetchImpl} />);
    const pw = await screen.findByLabelText("Password");
    expect(screen.queryByText(/Demo sign-in/)).toBeNull();
    await fireEvent.changeText(pw, "wrong-password");
    await fireEvent.press(screen.getByRole("button", { name: "SIGN IN" }));
    expect(await screen.findByText("invalid email or password")).toBeTruthy();
    await fireEvent.changeText(screen.getByLabelText("Password"), "right-password");
    await fireEvent.press(screen.getByRole("button", { name: "SIGN IN" }));
    expect(await screen.findByText("Arun Kumar")).toBeTruthy();
    expect(backend.calls).toContain("POST /api/v1/auth/login");
    expect(backend.calls).not.toContain("POST /api/v1/auth/dev-login");
  });
});
