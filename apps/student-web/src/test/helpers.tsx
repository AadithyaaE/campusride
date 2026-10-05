import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { ApiProvider } from "../api/ApiContext";
import type { BusOut } from "../api/types";
import { ApiClient } from "../api/client";
import * as fx from "./fixtures";

type Handler = (url: URL, init: RequestInit) => Response | Promise<Response>;

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * A fake `fetch` that answers like the real backend for the Phase 1 endpoints,
 * using the fake fixtures. Individual paths can be overridden.
 */
export function fakeBackend(overrides: Record<string, Handler> = {}) {
  const calls: string[] = [];
  // Stateful fake of the backend simulator controls.
  const sim = { ...fx.simStatus };
  const simCall = (patch: Partial<typeof sim>) => () => json(Object.assign(sim, patch));
  const routes: Record<string, Handler> = {
    "GET /api/v1/health": () => json(fx.health),
    "GET /api/v1/auth/config": () => json(fx.devAuth),
    "POST /api/v1/auth/dev-login": () => json(fx.token),
    "POST /api/v1/auth/login": (_url, init) =>
      (JSON.parse(String(init.body)) as { password?: string }).password === "right-password"
        ? json({ ...fx.token, auth_method: "password" })
        : json({ error: { code: "unauthorized", message: "invalid email or password" } }, 401),
    "GET /api/v1/me": () => json(fx.me),
    "GET /api/v1/stops": () => json(fx.stops),
    "GET /api/v1/routes": () => json(fx.routeSummaries),
    "GET /api/v1/students/me/assignment": () => json(fx.assignment),
    "GET /api/v1/buses": () => json(fx.buses),
    "GET /api/v1/students/me/stop/buses": () => json(fx.myStopBuses),
    "GET /api/v1/students/me/arrivals": () => json(fx.myArrivals),
    "GET /api/v1/students/me/bus-options": () => json(fx.myBusOptions),
    "GET /api/v1/students/me/commute-decision": () => json(fx.myCommute),
    "GET /api/v1/students/me/boarding": () => json(fx.myBoarding),
    "GET /api/v1/students/me/recovery-options": () => json(fx.recoveryNotNeeded),
    "GET /api/v1/alerts": () => json([]),
    // Feature 16: composed from the (overridable) endpoints above, like the backend aggregates them
    "GET /api/v1/students/me/commute": async (url, init) => {
      const part = async (key: string) => (await routes[key]!(url, init)).json();
      const [decision, recovery, boarding, buses, assignment] = await Promise.all([
        part("GET /api/v1/students/me/commute-decision"),
        part("GET /api/v1/students/me/recovery-options"),
        part("GET /api/v1/students/me/boarding"),
        part("GET /api/v1/buses"),
        part("GET /api/v1/students/me/assignment"),
      ]);
      const assigned = assignment.status === "assigned";
      const bus = assigned
        ? (buses as BusOut[]).find((b) => b.id === assignment.assignment.bus.id)
        : null;
      return json({
        student_id: fx.me.id,
        status: assigned ? "assigned" : "unassigned",
        phase: assigned ? "waiting" : "unassigned",
        phase_reason: assigned ? "Your bus is on its way." : "No bus assigned yet.",
        assignment: assigned ? assignment.assignment : null,
        bus: bus ?? null,
        trip: bus?.live?.trip_id
          ? {
              trip_id: bus.live.trip_id,
              status: "active",
              route_direction_id: bus.live.route_direction_id,
              direction: bus.live.direction,
              scheduled_start: "2030-01-07T01:45:00Z",
              actual_start: "2030-01-07T01:46:00Z",
              actual_end: null,
              end_reason: null,
            }
          : null,
        decision,
        recovery,
        boarding,
        alerts: [],
        computed_at: "2030-01-07T01:52:00Z",
      });
    },
    "GET /api/v1/students/me/history": () => json(fx.myHistory),
    "GET /api/v1/sim/status": () => json(sim),
    "POST /api/v1/sim/start": simCall({ paused: false, running: true }),
    "POST /api/v1/sim/pause": simCall({ paused: true, running: false }),
    "POST /api/v1/sim/reset": simCall({ sim_time: fx.simStatus.start_time }),
    "PUT /api/v1/sim/speed": async (_url, init) =>
      json(
        Object.assign(sim, { speed: (JSON.parse(String(init.body)) as { speed: number }).speed }),
      ),
    ...overrides,
  };
  const fetchImpl = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const key = `${init.method ?? "GET"} ${url.pathname}`;
    calls.push(key);
    const exact = routes[key];
    if (exact) return exact(url, init);
    const routeMatch = /^GET \/api\/v1\/routes\/([^/]+)$/.exec(key);
    if (routeMatch) {
      const r = fx.routeDetails.find((x) => x.id === decodeURIComponent(routeMatch[1]!));
      return r ? json(r) : json({ error: { code: "not_found", message: "route not found" } }, 404);
    }
    const stopRoutes = /^GET \/api\/v1\/stops\/([^/]+)\/routes$/.exec(key);
    if (stopRoutes) return json(fx.servicesAt(decodeURIComponent(stopRoutes[1]!)));
    return json({ error: { code: "not_found", message: `no fake for ${key}` } }, 404);
  }) as typeof fetch;
  return { fetchImpl, calls };
}

export function makeClient(fetchImpl: typeof fetch, token: string | null = "mock.test.token") {
  return new ApiClient({ baseUrl: "http://backend.test/api/v1", getToken: () => token, fetchImpl });
}

export function renderWithApi(ui: ReactElement, client: ApiClient) {
  return render(<ApiProvider client={client}>{ui}</ApiProvider>);
}

/** In-memory Storage for session / prototype-selection tests. */
export class MemoryStorage implements Storage {
  private data = new Map<string, string>();
  get length() {
    return this.data.size;
  }
  clear() {
    this.data.clear();
  }
  getItem(k: string) {
    return this.data.get(k) ?? null;
  }
  key(i: number) {
    return [...this.data.keys()][i] ?? null;
  }
  removeItem(k: string) {
    this.data.delete(k);
  }
  setItem(k: string, v: string) {
    this.data.set(k, v);
  }
}
