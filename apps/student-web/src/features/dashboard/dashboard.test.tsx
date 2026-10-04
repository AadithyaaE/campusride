import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../App";
import { ApiClient } from "../../api/client";
import type { BusOut } from "../../api/types";
import { FALLBACK_POLL_MS } from "../../data/liveFleet";
import type { MapViewProps } from "../../map/MapView";
import { SessionStore } from "../../session/sessionStore";
import * as fx from "../../test/fixtures";
import { fakeBackend, json, MemoryStorage } from "../../test/helpers";

const mapProps: { current: MapViewProps | null } = { current: null };
vi.mock("../../map/MapView", () => ({
  default: (props: MapViewProps) => {
    mapProps.current = props;
    return <div data-testid="map" />;
  },
}));

function signedInApp(overrides: Parameters<typeof fakeBackend>[0] = {}) {
  const storage = new MemoryStorage();
  const store = new SessionStore(storage);
  store.set({ token: "mock.saved", expiresAt: "2099-01-01T00:00:00Z", userId: fx.me.id });
  const backend = fakeBackend(overrides);
  const api = new ApiClient({
    baseUrl: "http://backend.test/api/v1",
    getToken: () => store.get()?.token ?? null,
    fetchImpl: backend.fetchImpl,
  });
  render(<App api={api} store={store} />);
  return { storage, backend };
}

const flush = () => act(async () => {});
const busMarker = (id: string) => mapProps.current?.buses.find((b) => b.id === id);
const pollOnce = () =>
  act(async () => {
    vi.advanceTimersByTime(FALLBACK_POLL_MS); // no live socket in these tests → fallback polling
  });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  mapProps.current = null;
  window.history.replaceState(null, "", "/");
});
afterEach(() => vi.useRealTimers());

describe("Dashboard — live state from the backend", () => {
  it("shows MY BUS from the backend's matching: stops, distance, approach state", async () => {
    const { backend } = signedInApp();
    const card = await screen.findByRole("region", { name: "My bus live" });
    expect(card).toHaveTextContent("BUS BX7"); // from /students/me/assignment
    expect(card).toHaveTextContent("On route"); // backend status
    expect(card).toHaveTextContent("On the way · next stop"); // backend proximity + stops_away
    expect(card).toHaveTextContent("Distance to my stop3.2 km"); // backend distance_to_stop_m
    // backend ETA as a whole-minute countdown + traffic + confidence (no browser formula)
    expect(within(card).getByLabelText("ETA 7 min")).toHaveTextContent("7 min");
    expect(card).toHaveTextContent("Moderate traffic");
    expect(card).toHaveTextContent("High confidence");
    expect(card).toHaveTextContent("Arrival (sim time)07:27"); // backend estimated_arrival_time, campus time
    expect(card).toHaveTextContent("Current stopTest Stop C"); // backend position.current_stop
    expect(card).toHaveTextContent("Next stopTest Stop B"); // backend position.next_stop
    expect(card).toHaveTextContent("Boarding stop Test Stop B");
    expect(within(card).getByLabelText("Occupancy 20 of 50")).toBeInTheDocument();
    expect(card).toHaveTextContent("Last updated 07:20:00 (sim time)");
    expect(backend.calls).toContain("GET /api/v1/students/me/arrivals");
    expect(backend.calls).toContain("GET /api/v1/buses");
    expect(screen.getByTitle("Your college-assigned boarding stop")).toHaveTextContent(
      "Boarding stop: Test Stop B",
    );
  });

  it("shows the backend's previous stop and approaching state", async () => {
    signedInApp({
      "GET /api/v1/students/me/arrivals": () =>
        json({
          ...fx.myArrivals,
          my_bus: fx.arrival(
            "BX7",
            { proximity: "approaching_stop", distance_to_stop_m: 600, stops_away: 1 },
            fx.eta(1),
            {
              position: {
                current_stop: { id: "X3", name: "Test Stop C", seq: 0 },
                previous_stop: { id: "XP", name: "Backend Previous Stop", seq: -1 },
                next_stop: { id: "X2", name: "Test Stop B", seq: 1 },
                at_stop: false,
                distance_to_next_stop_m: 600,
              },
            },
          ),
        }),
    });
    const card = await screen.findByRole("region", { name: "My bus live" });
    expect(card).toHaveTextContent("Approaching your stop · next stop");
    expect(card).toHaveTextContent("Distance to my stop600 m");
    expect(card).toHaveTextContent("previous stop Backend Previous Stop"); // displayed, not computed
  });

  it("direction-specific: assigned bus on the other direction is not shown as serving", async () => {
    signedInApp({
      "GET /api/v1/students/me/arrivals": () =>
        json({
          ...fx.myArrivals,
          my_bus_serving_stop: false,
          my_bus: fx.stopBus("BX7", null, {
            route_direction_id: "T2-E",
            direction: "from_campus",
            direction_label: "T2-E — From Campus",
          }),
        }),
    });
    const card = await screen.findByRole("region", { name: "My bus live" });
    expect(card).toHaveTextContent("Currently running T2-E — From Campus — not serving your stop");
    expect(card).toHaveTextContent("Distance to my stop—");
  });

  it("puts backend bus positions on the map and highlights only the assigned bus", async () => {
    signedInApp();
    await screen.findByRole("region", { name: "My bus live" });
    expect(mapProps.current?.buses.map((b) => b.id)).toEqual(["BX7", "BX8", "BX9"]);
    for (const bus of fx.buses) {
      expect(busMarker(bus.id)?.lnglat).toEqual(bus.live!.location.coordinates); // exactly the backend's
    }
    expect(mapProps.current?.buses.filter((b) => b.highlight).map((b) => b.id)).toEqual(["BX7"]);
    const badge = screen.getAllByRole("note").find((n) => n.classList.contains("map-sim-badge"));
    expect(badge).toHaveTextContent("Simulated live tracking");
  });

  it("polls the backend and reflects changing positions and matching", async () => {
    let n = 0;
    const moving = (): BusOut[] =>
      fx.buses.map((b) => (b.id === "BX7" ? { ...b, live: fx.live("T2", 1800 + 400 * n) } : b));
    const { backend } = signedInApp({
      "GET /api/v1/buses": () => json(moving()),
      "GET /api/v1/students/me/arrivals": () => {
        const d = 3200 - 400 * n;
        n += 1;
        return json({
          ...fx.myArrivals,
          my_bus: fx.arrival("BX7", { distance_to_stop_m: d, stop_offset_m: d }, fx.eta(7 - n)),
        });
      },
    });
    await screen.findByRole("region", { name: "My bus live" });
    const first = busMarker("BX7")!.lnglat;
    const count = () =>
      backend.calls.filter((c) => c === "GET /api/v1/students/me/arrivals").length;
    const pollsBefore = count();
    await pollOnce();
    await flush();
    expect(count()).toBe(pollsBefore + 1);
    expect(busMarker("BX7")!.lnglat).not.toEqual(first);
    const card = screen.getByRole("region", { name: "My bus live" });
    expect(card).toHaveTextContent("Distance to my stop2.8 km");
    expect(within(card).getByLabelText("ETA 5 min")).toBeInTheDocument(); // next poll's backend ETA
  });

  it("demo mode drives the backend simulator: pause, start, speed, reset", async () => {
    const { backend } = signedInApp();
    const panel = await screen.findByRole("region", { name: "Demo mode" });
    await flush();
    expect(panel).toHaveTextContent("Simulated live tracking");
    expect(panel).toHaveTextContent("Running");

    fireEvent.click(within(panel).getByRole("button", { name: "Pause simulation" }));
    await flush();
    expect(backend.calls).toContain("POST /api/v1/sim/pause");
    expect(panel).toHaveTextContent("Paused");
    expect(screen.getByRole("region", { name: "My bus live" })).toHaveTextContent(
      "Simulated · paused",
    );

    fireEvent.click(within(panel).getByRole("button", { name: "Start simulation" }));
    await flush();
    expect(backend.calls).toContain("POST /api/v1/sim/start");

    fireEvent.click(within(panel).getByRole("radio", { name: "20×" }));
    await flush();
    expect(backend.calls).toContain("PUT /api/v1/sim/speed");
    expect(within(panel).getByRole("radio", { name: "20×" })).toHaveAttribute(
      "aria-checked",
      "true",
    );

    fireEvent.click(within(panel).getByRole("button", { name: "Reset simulation" }));
    await flush();
    expect(backend.calls).toContain("POST /api/v1/sim/reset");
  });

  it("hides simulator controls when the backend says the user may not use them", async () => {
    signedInApp({
      "GET /api/v1/sim/status": () => json({ ...fx.simStatus, controls_allowed: false }),
    });
    const panel = await screen.findByRole("region", { name: "Demo mode" });
    await flush();
    expect(within(panel).queryByRole("button", { name: /simulation/ })).not.toBeInTheDocument();
    expect(panel).toHaveTextContent("administrators only");
  });

  it("lists OTHER buses serving my stop from the backend, apart from MY BUS", async () => {
    signedInApp();
    const list = await screen.findByRole("list", { name: "Other buses at my stop" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector(".bus-id")?.textContent)).toEqual(["BX8", "BX9"]);
    expect(rows[0]).toHaveTextContent("Test Line One"); // route
    expect(rows[0]).toHaveTextContent("To Campus"); // direction
    expect(rows[0]).toHaveTextContent("Current: Test Stop A · Next: Test Stop B");
    expect(rows[0]).toHaveTextContent("Approaching your stop 800 m to my stop · next stop");
    expect(within(rows[0]!).getByLabelText("Occupancy 37 of 40")).toBeInTheDocument();
    // the browser no longer labels buses itself — the backend comparison does (Bus options)
    expect(list).not.toHaveTextContent(/Recommended/);
    // ordered by BACKEND ETA, shown as countdowns with traffic / confidence
    expect(within(rows[0]!).getByLabelText("ETA 2 min")).toHaveTextContent("Low traffic");
    expect(within(rows[0]!).getByLabelText("ETA 2 min")).toHaveTextContent("Medium confidence");
    expect(within(rows[1]!).getByLabelText("ETA 14 min")).toHaveTextContent("Low confidence");
    expect(within(list).queryByText("BX7")).not.toBeInTheDocument(); // my bus is not "other"
  });

  it("marks buses that serve my stop on the map (per backend matching)", async () => {
    signedInApp();
    await screen.findByRole("list", { name: "Other buses at my stop" });
    expect(busMarker("BX7")).toMatchObject({ highlight: true, serving: false });
    expect(busMarker("BX8")).toMatchObject({ highlight: false, serving: true });
    expect(busMarker("BX9")).toMatchObject({ highlight: false, serving: true });
    expect(mapProps.current?.myStopId).toBe("X2"); // boarding stop highlighted
  });

  it("shows the BACKEND decision and the BACKEND alerts", async () => {
    signedInApp({
      "GET /api/v1/alerts": () => json(fx.myAlerts),
      "GET /api/v1/students/me/arrivals": () =>
        json({
          ...fx.myArrivals,
          my_bus: fx.arrival("BX7", {}, fx.eta(7), { schedule_status: "delayed", delay_s: 420 }),
          arrivals: [
            fx.arrival(
              "BX8",
              { proximity: "approaching_stop", distance_to_stop_m: 800 },
              fx.eta(2),
              { occupancy: 37 },
            ),
          ],
        }),
    });
    const decision = await screen.findByRole("region", { name: "Will I make my bus?" });
    expect(within(decision).getByRole("status")).toHaveTextContent("YES");
    expect(decision).toHaveTextContent("Can I catch bus BX7?");
    expect(decision).toHaveTextContent("Rule-based estimate from the backend");
    const alerts = await screen.findByRole("list", { name: "Alert list" });
    expect(alerts).toHaveTextContent("Bus BX7 is running 8 minutes late.");
    expect(alerts).toHaveTextContent("Bus BX7 reaches your stop (Test Stop B) in 3 minutes.");
    // the header badge counts UNREAD backend alerts (2 of 3)
    expect(screen.getByRole("button", { name: "Notifications (2)" })).toBeInTheDocument();
  });

  it("shows the BACKEND bus comparison and highlights a picked bus on the map", async () => {
    const { backend } = signedInApp();
    const options = await screen.findByRole("region", { name: "Bus options" });
    expect(backend.calls).toContain("GET /api/v1/students/me/bus-options");
    const bx9 = within(options).getByRole("button", { name: "Bus BX9" });
    expect(bx9).toHaveTextContent("Least crowded");
    expect(within(options).getByRole("button", { name: "Bus BX7" })).toHaveTextContent("Assigned");
    expect(busMarker("BX9")).toMatchObject({ focused: false });
    fireEvent.click(bx9);
    expect(busMarker("BX9")).toMatchObject({ focused: true, serving: true });
    expect(busMarker("BX7")).toMatchObject({ highlight: true, focused: false }); // mine stays mine
    fireEvent.click(within(options).getByRole("button", { name: "Bus BX9" }));
    expect(busMarker("BX9")).toMatchObject({ focused: false });
  });

  it("updates the comparison on the next poll (indicators can move)", async () => {
    let n = 0;
    signedInApp({
      "GET /api/v1/students/me/bus-options": () => {
        n += 1;
        const [a, b, c] = fx.myBusOptions.options;
        return json(
          n === 1
            ? fx.myBusOptions
            : {
                ...fx.myBusOptions,
                options: [
                  { ...a!, indicators: ["FASTEST"] },
                  { ...b!, indicators: ["ASSIGNED"] },
                  { ...c!, indicators: ["LEAST_CROWDED", "BEST_ALTERNATIVE"] },
                ],
              },
        );
      },
    });
    const options = await screen.findByRole("region", { name: "Bus options" });
    expect(within(options).getByRole("button", { name: "Bus BX7" })).toHaveTextContent(
      "Best alternative",
    );
    await pollOnce();
    await flush();
    expect(within(options).getByRole("button", { name: "Bus BX7" })).not.toHaveTextContent(
      "Best alternative",
    );
    expect(within(options).getByRole("button", { name: "Bus BX9" })).toHaveTextContent(
      "Best alternative",
    );
  });

  it("polls the BACKEND commute decision and shows its change on the next poll", async () => {
    let n = 0;
    const { backend } = signedInApp({
      "GET /api/v1/students/me/commute-decision": () => {
        n += 1;
        return json(
          n === 1
            ? fx.myCommute
            : fx.commute({
                decision: "MISSED",
                reason: "Your assigned bus has already passed your stop.",
                eta: null,
              }),
        );
      },
    });
    const card = await screen.findByRole("region", { name: "Will I make my bus?" });
    expect(backend.calls).toContain("GET /api/v1/students/me/commute-decision");
    expect(within(card).getByRole("status")).toHaveAccessibleName("Decision: YES");
    await pollOnce();
    await flush();
    expect(
      within(screen.getByRole("region", { name: "Will I make my bus?" })).getByRole("status"),
    ).toHaveAccessibleName("Decision: MISSED");
    expect(backend.calls.filter((c) => c.includes("commute-decision?"))).toEqual([]); // no bus/stop params
  });

  it("shows the BACKEND recovery card only when needed, and follows it on every poll", async () => {
    let n = 0;
    const { backend } = signedInApp({
      "GET /api/v1/students/me/recovery-options": () => {
        n += 1;
        if (n === 1) return json(fx.recoveryNotNeeded); // assigned bus comfortably catchable
        if (n === 2) return json(fx.recovery()); // → at risk: BX8 recommended, BX9 also
        // → BX8 filled up: the backend drops it and recommends BX9
        return json(
          fx.recovery({
            recommended: fx.recoveryOption("BX9", { eta_minutes: 14 }),
            alternatives: [],
            excluded: [{ bus_id: "BX8", reason: "full" }],
          }),
        );
      },
    });
    await screen.findByRole("region", { name: "My bus live" });
    expect(screen.queryByRole("region", { name: "Missed-bus recovery" })).not.toBeInTheDocument();
    await pollOnce();
    await flush();
    const card = screen.getByRole("region", { name: "Missed-bus recovery" });
    expect(card).toHaveTextContent("Try BUS BX8 instead");
    // the other dashboard sections stay visible
    expect(screen.getByRole("region", { name: "My bus live" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Will I make my bus?" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Bus options" })).toBeInTheDocument();
    await pollOnce();
    await flush();
    const after = screen.getByRole("region", { name: "Missed-bus recovery" });
    expect(after).toHaveTextContent("Try BUS BX9 instead");
    expect(after).not.toHaveTextContent("BX8");
    expect(backend.calls).toContain("GET /api/v1/students/me/recovery-options");
    expect(backend.calls.filter((c) => c.includes("recovery-options?"))).toEqual([]); // no overrides
  });

  it("shows a backend MAJOR deviation on my bus without hiding commute, recovery or occupancy", async () => {
    signedInApp({
      "GET /api/v1/students/me/arrivals": () =>
        json({
          ...fx.myArrivals,
          my_bus: fx.arrival(
            "BX7",
            { distance_to_stop_m: 3200, stop_offset_m: 3200, stops_away: 1 },
            fx.eta(7),
            { status: "deviated", route_status: "MAJOR_DEVIATION", deviation_distance_m: 312.4 },
          ),
        }),
      "GET /api/v1/students/me/recovery-options": () => json(fx.recovery()),
    });
    const mine = await screen.findByRole("region", { name: "My bus live" });
    expect(mine).toHaveTextContent("Major deviation · 312 m off route");
    expect(within(mine).getByRole("alert")).toHaveTextContent(
      "Your bus is currently 312 m from its planned route.",
    );
    expect(within(mine).getByLabelText("Live occupancy")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Will I make my bus?" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Missed-bus recovery" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Bus options" })).toBeInTheDocument();
  });

  it("polls BACKEND alerts and marks one read through the backend", async () => {
    let n = 0;
    let readId: string | null = null;
    const { backend } = signedInApp({
      "GET /api/v1/alerts": () => {
        n += 1;
        // a new backend alert appears on the next poll
        return json(n === 1 ? fx.myAlerts.slice(1) : fx.myAlerts);
      },
      [`PATCH /api/v1/alerts/${fx.myAlerts[0]!.alert_id}/read`]: () => {
        readId = fx.myAlerts[0]!.alert_id;
        return json({ ...fx.myAlerts[0]!, read: true });
      },
    });
    await screen.findByRole("list", { name: "Alert list" });
    expect(screen.getByRole("button", { name: "Notifications (1)" })).toBeInTheDocument();
    await pollOnce();
    await flush();
    expect(screen.getByRole("button", { name: "Notifications (2)" })).toBeInTheDocument();
    const panel = screen.getByRole("region", { name: "Notifications" });
    fireEvent.click(within(panel).getByRole("button", { name: "Mark BUS APPROACHING read" }));
    await flush();
    expect(readId).toBe(fx.myAlerts[0]!.alert_id);
    expect(screen.getByRole("button", { name: "Notifications (1)" })).toBeInTheDocument();
    expect(backend.calls.some((c) => c.startsWith("GET /api/v1/alerts"))).toBe(true);
    // the other dashboard cards stay
    expect(screen.getByRole("region", { name: "My bus live" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Will I make my bus?" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Bus options" })).toBeInTheDocument();
  });

  it("shows no bus options to an unassigned student", async () => {
    signedInApp({
      "GET /api/v1/students/me/assignment": () => json(fx.unassigned),
      "GET /api/v1/students/me/arrivals": () => json(fx.myArrivalsUnassigned),
      "GET /api/v1/students/me/bus-options": () => json(fx.myBusOptionsUnassigned),
      "GET /api/v1/students/me/commute-decision": () => json(fx.myCommuteUnassigned),
      "GET /api/v1/students/me/recovery-options": () =>
        json(
          fx.recovery({ status: "unassigned", trigger: null, recommended: null, alternatives: [] }),
        ),
    });
    await screen.findByText("Your bus assignment is not available yet.");
    expect(screen.queryByRole("region", { name: "Bus options" })).not.toBeInTheDocument();
  });

  it("shows the BACKEND occupancy of my bus and refreshes it after a QR scan", async () => {
    let scanned = false;
    const mine = (occupancy: number, pct: number, seats: number) =>
      json({
        ...fx.myArrivals,
        my_bus: fx.arrival(
          "BX7",
          { distance_to_stop_m: 3200, stop_offset_m: 3200, stops_away: 1 },
          fx.eta(7),
          // as reported by the backend — the dashboard never derives these
          { occupancy, occupancy_percentage: pct, available_seats: seats },
        ),
      });
    const { backend } = signedInApp({
      "GET /api/v1/students/me/arrivals": () => (scanned ? mine(39, 78, 11) : mine(38, 76, 12)),
      "POST /api/v1/boarding/scan": () => {
        scanned = true;
        return json(fx.scanResult());
      },
    });
    const card = await screen.findByRole("region", { name: "My bus live" });
    expect(within(card).getByLabelText("Live occupancy")).toHaveTextContent(
      "38 / 50 passengers · 76% occupied · 12 seats available",
    );
    const qa = screen.getByRole("region", { name: "Quick actions" });
    fireEvent.click(within(qa).getByRole("button", { name: /Scan Boarding QR/ }));
    const dialog = screen.getByRole("dialog", { name: "Scan Boarding QR" });
    fireEvent.click(await within(dialog).findByRole("button", { name: "Simulate Scan" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Boarding recorded");
    await flush();
    expect(backend.calls).toContain("POST /api/v1/boarding/scan");
    expect(
      within(screen.getByRole("region", { name: "My bus live" })).getByLabelText("Live occupancy"),
    ).toHaveTextContent("39 / 50 passengers · 78% occupied · 11 seats available");
  });

  it("offers no way to change the assignment and never writes it anywhere", async () => {
    const { backend, storage } = signedInApp();
    const qa = await screen.findByRole("region", { name: "Quick actions" });
    expect(
      screen.queryByRole("button", { name: /change (stop|bus|route)/i }),
    ).not.toBeInTheDocument();
    fireEvent.click(within(qa).getByRole("button", { name: /Scan Boarding QR/ }));
    const dialog = screen.getByRole("dialog", { name: "Scan Boarding QR" });
    expect(
      await within(dialog).findByRole("button", { name: "Simulate Scan" }),
    ).toBeInTheDocument();
    // the scanner offers no bus / stop / student picker
    expect(within(dialog).queryByRole("combobox")).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await pollOnce();
    await flush();
    expect(backend.calls.filter((c) => c.includes("/students/") && !c.startsWith("GET"))).toEqual(
      [],
    );
    const keys = Array.from({ length: storage.length }, (_, i) => storage.key(i));
    expect(keys).toEqual(["campusride.session"]);
  });
});

describe("Dashboard — unassigned student", () => {
  it("never invents a bus: no My-bus card, no highlighted bus", async () => {
    const { backend } = signedInApp({
      "GET /api/v1/students/me/assignment": () => json(fx.unassigned),
      "GET /api/v1/students/me/arrivals": () => json(fx.myArrivalsUnassigned),
    });
    expect(
      await screen.findAllByText("Your bus assignment is not available yet."),
    ).not.toHaveLength(0);
    await flush();
    expect(screen.queryByRole("region", { name: "My bus live" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Will I make my bus?" })).not.toBeInTheDocument();
    expect(screen.queryByTitle("Your college-assigned boarding stop")).not.toBeInTheDocument();
    // The simulator runs globally, so other buses may show — but none is "theirs".
    expect(mapProps.current?.buses.some((b) => b.highlight || b.serving)).toBe(false);
    expect(screen.queryByRole("list", { name: "Other buses at my stop" })).not.toBeInTheDocument();
    expect(backend.calls).toContain("GET /api/v1/students/me/arrivals");
    expect(screen.getByRole("region", { name: "Demo mode" })).toBeInTheDocument();
  });
});

describe("guardrails", () => {
  const appSources = import.meta.glob(
    ["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}", "!/src/**/*.gen.ts", "!/src/test/**"],
    { query: "?raw", import: "default", eager: true },
  ) as Record<string, string>;

  it("opens WebSockets only in the one realtime client (Feature 14)", () => {
    expect(Object.keys(appSources).length).toBeGreaterThan(20);
    for (const [file, src] of Object.entries(appSources)) {
      if (file === "/src/realtime/client.ts") continue;
      expect(src, file).not.toMatch(/new\s+WebSocket|socket\.io|EventSource/);
    }
    expect(appSources["/src/realtime/client.ts"]).toMatch(/new WebSocket\(/);
  });

  it("has no browser-side bus simulation", () => {
    expect(Object.keys(appSources).filter((f) => f.startsWith("/src/demo/"))).toEqual([]);
    for (const [file, src] of Object.entries(appSources)) {
      expect(src, file).not.toMatch(/demoSnapshot|buildDemoFleet|useDemoLive|pointAt\(/);
    }
  });

  it("does no stop/route matching in the browser (backend is authoritative)", () => {
    const ui = Object.entries(appSources).filter(
      ([f]) => f.startsWith("/src/features/") || f.startsWith("/src/shell/"),
    );
    expect(ui.length).toBeGreaterThan(5);
    for (const [file, src] of ui) {
      // distance_along_m is the raw input matching would need; the UI must only use backend results
      expect(src, file).not.toMatch(/distance_along_m|stops\.find\(\(s\) => s\.distance/);
    }
  });
});
