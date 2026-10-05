import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../App";
import { ApiClient } from "../../api/client";
import type { StudentCommuteOut } from "../../api/types";
import { SessionStore } from "../../session/sessionStore";
import { FakeWebSocket } from "../../test/fakeSocket";
import * as fx from "../../test/fixtures";
import { fakeBackend, json, MemoryStorage } from "../../test/helpers";

vi.mock("../../map/MapView", () => ({
  default: () => <div data-testid="map" />,
}));

const wait = (ms: number) => act(() => new Promise((r) => setTimeout(r, ms)));
const settle = async () => {
  for (let i = 0; i < 5; i++) await wait(0);
};

type Overrides = Parameters<typeof fakeBackend>[0];

/** Base commute = what the composed fake returns; tests override phase/trip/boarding. */
async function baseCommute(): Promise<StudentCommuteOut> {
  const b = fakeBackend();
  const r = await b.fetchImpl("http://backend.test/api/v1/students/me/commute", {});
  return (await r.json()) as StudentCommuteOut;
}

function setup(overrides: Overrides = {}) {
  const store = new SessionStore(new MemoryStorage());
  store.set({ token: "mock.saved", expiresAt: "2099-01-01T00:00:00Z", userId: fx.me.id });
  const backend = fakeBackend(overrides);
  const api = new ApiClient({
    baseUrl: "http://backend.test/api/v1",
    getToken: () => store.get()?.token ?? null,
    onUnauthorized: () => store.clear(),
    fetchImpl: backend.fetchImpl,
  });
  render(<App api={api} store={store} />);
  const count = (k: string) => backend.calls.filter((c) => c === k).length;
  return { backend, store, count };
}

const today = () => screen.findByRole("region", { name: "Today's commute" });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  window.history.replaceState(null, "", "/");
});
afterEach(() => vi.useRealTimers());

describe("Today's Commute (Feature 16, backend /students/me/commute)", () => {
  it("shows the authenticated student's bus, stop, ETA, decision, occupancy and phase", async () => {
    const { backend } = setup();
    const card = await today();
    expect(within(card).getByRole("status")).toHaveTextContent("Waiting");
    expect(card).toHaveTextContent("Your bus is on its way.");
    expect(card).toHaveTextContent("Bus BX7");
    expect(card).toHaveTextContent("Boarding at Test Stop B");
    expect(card).toHaveTextContent("Will I make it?You'll make it");
    expect(within(card).getByLabelText(/^ETA \d+ min$/)).toBeInTheDocument(); // backend ETA
    expect(card).toHaveTextContent(/\d+\/50/);
    expect(card).toHaveTextContent(/seats available/);
    // exactly one clear primary action
    expect(within(card).getAllByRole("button")).toHaveLength(1);
    expect(
      within(card).getByRole("button", { name: "Show my bus on the map" }),
    ).toBeInTheDocument();
    expect(backend.calls).toContain("GET /api/v1/students/me/commute");
    // the browser never asks for another student's data
    expect(backend.calls.filter((c) => c.includes("/students/U-"))).toEqual([]);
  });

  it.each([
    ["no_trip", "No active trip"],
    ["approaching", "Approaching"],
    ["at_stop", "At your stop"],
    ["missed", "Missed"],
  ] as const)("renders the backend phase %s", async (phase, label) => {
    const base = await baseCommute();
    setup({
      "GET /api/v1/students/me/commute": () =>
        json({ ...base, phase, phase_reason: `reason ${phase}` }),
    });
    const card = await today();
    expect(within(card).getByRole("status")).toHaveTextContent(label);
    expect(card).toHaveTextContent(`reason ${phase}`);
  });

  it("boarded state shows the boarding time and that it was a simulated QR scan", async () => {
    const base = await baseCommute();
    const boarded = {
      ...base,
      phase: "on_board",
      phase_reason: "You're on board — the trip is in progress.",
      boarding: {
        ...base.boarding,
        ready: false,
        boarded: {
          boarding_id: "BRD-1",
          student_id: fx.me.id,
          bus_id: "BX7",
          trip_id: "T-TEST-T2",
          stop_id: "X2",
          timestamp: "2030-01-07T02:01:00Z",
          scanner: "simulated",
        },
      },
    };
    setup({ "GET /api/v1/students/me/commute": () => json(boarded) });
    const card = await today();
    expect(within(card).getByRole("status")).toHaveTextContent("On board");
    expect(card).toHaveTextContent(/Boarded · \d{1,2}:\d\d (AM|PM)/); // human time
    expect(card).not.toHaveTextContent("2030-01-07T"); // never a raw timestamp
  });

  it("a completed trip the student boarded never also shows a missed-bus card", async () => {
    const base = await baseCommute();
    const done = {
      ...base,
      phase: "completed",
      phase_reason: "You boarded this trip and it has finished.",
      boarding: {
        ...base.boarding,
        ready: false,
        boarded: {
          boarding_id: "BRD-1",
          student_id: fx.me.id,
          bus_id: "BX7",
          trip_id: "T-TEST-T2",
          stop_id: "X2",
          timestamp: "2030-01-07T02:01:00Z",
          scanner: "simulated",
        },
      },
    };
    setup({
      "GET /api/v1/students/me/commute": () => json(done),
      "GET /api/v1/students/me/recovery-options": () =>
        json(fx.recovery({ status: "no_alternative", trigger: "missed", recommended: null })),
    });
    const card = await today();
    await settle();
    expect(card).toHaveTextContent("Trip complete");
    expect(screen.queryByRole("region", { name: "Missed-bus recovery" })).not.toBeInTheDocument();
  });

  it("missed with an alternative offers the backend's recovery", async () => {
    const base = await baseCommute();
    setup({
      "GET /api/v1/students/me/commute": () =>
        json({
          ...base,
          phase: "recovery_available",
          phase_reason: "You've missed your bus — another bus can still get you there.",
        }),
    });
    const card = await today();
    expect(within(card).getByRole("status")).toHaveTextContent("Alternative available");
    expect(within(card).getByRole("button", { name: "View recovery options" })).toBeInTheDocument();
  });

  it("boarding through the simulated scanner updates the backend phase immediately", async () => {
    const base = await baseCommute();
    let boarded = false;
    setup({
      "POST /api/v1/boarding/scan": () => {
        boarded = true;
        return json(fx.scanResult());
      },
      "GET /api/v1/students/me/commute": () =>
        json(
          boarded
            ? {
                ...base,
                phase: "on_board",
                phase_reason: "You're on board — the trip is in progress.",
              }
            : base,
        ),
    });
    await today();
    fireEvent.click(await screen.findByRole("button", { name: /Scan Boarding QR/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Simulate Scan" }));
    await settle();
    expect(within(await today()).getByRole("status")).toHaveTextContent("On board");
  });

  it("re-fetches the commute when the backend pushes the student's own boarding", async () => {
    const { count } = setup();
    await today();
    const sock = FakeWebSocket.last;
    await act(async () => sock.accept({ role: "student", heartbeat_s: 20 }));
    await settle();
    const before = count("GET /api/v1/students/me/commute");
    await act(async () => {
      sock.emit("boarding.updated", {
        trip_id: "T-TEST-T2",
        bus_id: "BX7",
        stop_id: "X2",
        student_id: fx.me.id,
      });
    });
    await wait(1_700); // throttled derived refresh
    expect(count("GET /api/v1/students/me/commute")).toBe(before + 1);
  });

  it("shows an error when the backend can't be reached and signs out on 401", async () => {
    const down = setup({
      "GET /api/v1/students/me/commute": () => json({ error: { code: "x", message: "boom" } }, 500),
    });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    down.store.clear();
    document.body.innerHTML = "";
    const { store } = setup({
      "GET /api/v1/students/me/commute": () =>
        json({ error: { code: "unauthorized", message: "account is disabled" } }, 401),
    });
    await settle();
    await settle();
    expect(store.get()).toBeNull();
    expect(await screen.findByRole("form", { name: "Student sign in" })).toBeInTheDocument();
  });
});

describe("Recent commutes (Feature 16, backend /students/me/history)", () => {
  it("lists the backend history with outcomes, boarding time and simulated-QR labels", async () => {
    setup();
    const section = await screen.findByRole("region", { name: "Recent commutes" });
    const first = await within(section).findByRole("listitem", { name: "Commute T-TEST-T2-0715" });
    expect(first).toHaveTextContent("Boarded");
    expect(first).toHaveTextContent("BUS BX7 · T2 — To Campus · Test Stop B");
    expect(first).toHaveTextContent(/boarded \d{1,2}:\d\d (AM|PM) · demo QR scan/);
    const second = within(section).getByRole("listitem", { name: "Commute T-TEST-T2-0715-PREV" });
    expect(second).toHaveTextContent("Trip ended early");
    expect(second).toHaveTextContent("ended early by the driver");
  });

  it("empty history explains when trips will appear", async () => {
    setup({ "GET /api/v1/students/me/history": () => json({ ...fx.myHistory, entries: [] }) });
    const section = await screen.findByRole("region", { name: "Recent commutes" });
    expect(await within(section).findByText(/No recent commutes yet/)).toBeInTheDocument();
  });

  it("re-fetches history only when today's commute changes (no timer polling)", async () => {
    const base = await baseCommute();
    let phase: string = "on_board";
    const { count } = setup({ "GET /api/v1/students/me/commute": () => json({ ...base, phase }) });
    await screen.findByRole("region", { name: "Recent commutes" });
    await settle();
    const n = count("GET /api/v1/students/me/history");
    expect(n).toBe(1);
    const sock = FakeWebSocket.last;
    await act(async () => sock.accept({ role: "student", heartbeat_s: 20 }));
    await settle(); // re-sync after connecting: same phase → no history refetch
    expect(count("GET /api/v1/students/me/history")).toBe(1);
    phase = "completed";
    await act(async () => {
      sock.emit("trip.completed", { trip_id: "T-TEST-T2", bus_id: "BX7" });
    });
    await wait(1_700);
    await settle();
    expect(count("GET /api/v1/students/me/history")).toBe(2);
  });
});
