/** A fake CampusRide backend for Driver App tests (answers like the real endpoints). */
import type { DriverDashboard } from "../api/client";

export type Handler = (init: RequestInit) => Response | Promise<Response>;

export const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

export const errorJson = (status: number, code: string, message = code): Response =>
  json({ error: { code, message } }, status);

/** A backend `GET /driver/me` answer. Defaults: Arun Kumar, Bus B07, READY. */
export function dash(over: Partial<DriverDashboard> = {}): DriverDashboard {
  return {
    driver: { id: "D07", name: "Arun Kumar", phone: "+91 90000 00007" },
    bus: { id: "B07", number: "B07", reg_no: "TN 00 CR 1007", capacity: 50 },
    route: {
      id: "R4",
      name: "Guindy – Taramani",
      color: "#7c3aed",
      route_direction_id: "R4",
      direction: "to_campus",
      label: "R4 — To Campus",
    },
    trip: {
      id: "T-20261005-R4-0715",
      status: "scheduled",
      scheduled_start: "2026-10-05T01:45:00Z",
      actual_start: null,
      actual_end: null,
      first_stop: "Guindy",
      last_stop: "Campus",
    },
    trip_state: "READY",
    control: "driver",
    can_start: true,
    can_stop: false,
    next_stop: "Guindy",
    gps: "LIVE",
    gps_source: "simulated",
    live: {
      location: { lat: 13.0067, lon: 80.2206 },
      speed_kmh: 0,
      heading_deg: 90,
      bus_status: "at_depot",
      current_stop: "Guindy",
      next_stop: "Little Mount",
      occupancy: 6,
      capacity: 50,
      available_seats: 44,
      occupancy_percentage: 12,
      delay_minutes: 0,
      schedule_status: "on_time",
      route_status: "NORMAL",
      deviation_distance_m: 3.1,
      last_fix_at: "2026-10-05T01:45:00Z",
    },
    message: null,
    ...over,
  };
}

/** The same bus after Start Trip, as the backend reports it. */
export function activeDash(over: Partial<DriverDashboard> = {}): DriverDashboard {
  const base = dash();
  return dash({
    trip_state: "ACTIVE",
    can_start: false,
    can_stop: true,
    trip: { ...base.trip!, status: "active", actual_start: "2026-10-05T01:46:00Z" },
    next_stop: "Library Gate",
    live: {
      ...base.live!,
      speed_kmh: 32,
      bus_status: "en_route",
      next_stop: "Library Gate",
      occupancy: 38,
      available_seats: 12,
      occupancy_percentage: 76,
    },
    ...over,
  });
}

export const DEV_AUTH = {
  mode: "dev",
  development: true,
  dev_login: true,
  password_login: false,
  external_provider: false,
  oidc_issuer: null,
};
export const PASSWORD_AUTH = {
  ...DEV_AUTH,
  mode: "password",
  development: false,
  dev_login: false,
  password_login: true,
};

const driverToken = (method: "dev" | "password") => ({
  access_token: "mock.driver",
  token_type: "bearer",
  expires_at: "2099-01-01T00:00:00Z",
  auth_method: method,
  user: {
    id: "U-D07",
    role: "driver",
    name: "Arun Kumar",
    email: "driver07@campusride.demo",
    active: true,
  },
});

export function fakeBackend(overrides: Record<string, Handler> = {}) {
  const calls: string[] = [];
  const routes: Record<string, Handler> = {
    "GET /api/v1/auth/config": () => json(DEV_AUTH),
    "POST /api/v1/auth/dev-login": () => json(driverToken("dev")),
    "POST /api/v1/auth/login": (init) =>
      (JSON.parse(String(init.body)) as { password?: string }).password === "right-password"
        ? json(driverToken("password"))
        : errorJson(401, "unauthorized", "invalid email or password"),
    "GET /api/v1/me": () =>
      json({ id: "U-D07", role: "driver", name: "Arun Kumar", email: "driver07@campusride.demo" }),
    "GET /api/v1/driver/me": () => json(dash()),
    "POST /api/v1/driver/trip/start": () => json(activeDash()),
    "POST /api/v1/driver/trip/stop": () =>
      json(dash({ trip: { ...dash().trip!, id: "T-20261005-R4-1715" }, next_stop: "Campus" })),
    "POST /api/v1/driver/simulate-gps": () => json(activeDash()),
    "GET /api/v1/driver/route": () =>
      json({
        route: dash().route,
        trip_id: "T-20261005-R4-0715",
        stops: [
          { seq: 0, stop_id: "S20", name: "Guindy", state: "passed" },
          { seq: 1, stop_id: "S21", name: "Little Mount", state: "current" },
          { seq: 2, stop_id: "S22", name: "Library Gate", state: "next" },
          { seq: 3, stop_id: "S99", name: "Campus", state: "upcoming" },
        ],
        bus_location: { lat: 13.0, lon: 80.22 },
        path: null,
      }),
    "GET /api/v1/buses/B07/occupancy": () =>
      json({
        bus_id: "B07",
        trip_id: "T-20261005-R4-0715",
        occupancy: 38,
        capacity: 50,
        available_seats: 12,
        occupancy_percentage: 76,
        baseline: 37,
        boarded: 1,
        source: "synthetic_baseline+qr",
        updated_at: "2026-10-05T01:50:00Z",
      }),
    "GET /api/v1/trips/T-20261005-R4-0715/boarding": () =>
      json({
        trip_id: "T-20261005-R4-0715",
        bus_id: "B07",
        route_direction_id: "R4",
        total_boarded: 1,
        visibility: "count_only",
        events: [],
      }),
    ...overrides,
  };
  const fetchImpl: typeof fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    const key = `${init.method ?? "GET"} ${url.pathname}`;
    calls.push(key);
    const handler = routes[key];
    return handler ? handler(init) : errorJson(404, "not_found", key);
  };
  return { fetchImpl, calls };
}
