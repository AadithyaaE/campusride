/** Fake CampusRide backend for admin-web tests: canned `/admin/*`, `/alerts`, `/routes` responses. */
import type {
  AdminAnalytics,
  AdminFleet,
  AdminOverview,
  AdminRoute,
  AdminSchedule,
  AlertOut,
  FleetBus,
  RouteDetail,
  RouteStatusResponse,
  TripBoardingOut,
} from "../api/client";

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

export function fleetBus(id: string, over: Partial<FleetBus> = {}): FleetBus {
  return {
    bus_id: id,
    reg_no: `TN 00 CR ${id}`,
    source: "sim",
    fleet_status: "active",
    route_id: "R1",
    route_name: "Tambaram",
    route_color: "#2563eb",
    driver: { id: `D${id.slice(1)}`, name: `Driver ${id}` },
    operational_status: "active",
    bus_status: "en_route",
    trip_id: `T-${id}`,
    trip_status: "active",
    route_direction_id: "R1",
    direction: "to_campus",
    direction_label: "R1 — To Campus",
    location: { lat: 12.92, lon: 80.12 },
    heading_deg: 90,
    speed_kmh: 32,
    current_stop: { id: "S01", name: "Tambaram Station" },
    next_stop: { id: "S02", name: "Library Gate" },
    eta_next_stop_min: 6,
    eta_status: "predicted",
    eta_confidence: "high",
    delay_s: 60,
    delay_min: 1,
    is_delayed: false,
    occupancy: 38,
    capacity: 50,
    available_seats: 12,
    occupancy_percentage: 76,
    crowding: "Medium",
    boarded_count: 0,
    route_status: "NORMAL",
    deviation_distance_m: 4.2,
    route_progress: 0.4,
    gps: "LIVE",
    gps_age_s: 3,
    last_updated: "2026-10-05T02:10:00Z",
    active_alerts: [],
    ...over,
  };
}

export const FLEET_BUSES: FleetBus[] = [
  fleetBus("B07", { route_id: "R4", route_name: "Guindy – Taramani", route_color: "#16a34a" }),
  fleetBus("B12", {
    speed_kmh: 28,
    eta_next_stop_min: 9,
    next_stop: { id: "S03", name: "Main Gate" },
    occupancy: 24,
    available_seats: 26,
    occupancy_percentage: 48,
    crowding: "Low",
  }),
  fleetBus("B15", {
    route_id: "R2",
    route_name: "Velachery",
    operational_status: "delayed",
    speed_kmh: 18,
    eta_next_stop_min: 15,
    delay_s: 480,
    delay_min: 8,
    is_delayed: true,
    occupancy: 41,
    available_seats: 9,
    occupancy_percentage: 82,
    crowding: "High",
    active_alerts: [
      {
        alert_id: "A-DELAY-B15",
        type: "BUS_DELAYED",
        severity: "warning",
        title: "BUS DELAYED",
        message: "Bus B15 is running 8 minutes late (R2).",
      },
    ],
  }),
  fleetBus("B05", {
    route_id: "R3",
    route_name: "Thiruvanmiyur – OMR",
    operational_status: "deviated",
    bus_status: "deviated",
    route_status: "MAJOR_DEVIATION",
    deviation_distance_m: 303.4,
    active_alerts: [
      {
        alert_id: "A-DEV-B05",
        type: "ROUTE_DEVIATION",
        severity: "critical",
        title: "ROUTE DEVIATION",
        message: "BUS B05 is 303 m off its planned route.",
      },
    ],
  }),
  fleetBus("B06", {
    route_id: "R3",
    route_name: "Thiruvanmiyur – OMR",
    route_status: "MINOR_DEVIATION",
    deviation_distance_m: 92.8,
  }),
  fleetBus("B09", {
    route_id: "R5",
    operational_status: "idle",
    bus_status: null,
    trip_id: null,
    trip_status: null,
    location: null,
    speed_kmh: null,
    current_stop: null,
    next_stop: null,
    eta_next_stop_min: null,
    eta_status: null,
    eta_confidence: null,
    delay_s: null,
    delay_min: null,
    occupancy: null,
    available_seats: null,
    occupancy_percentage: null,
    crowding: "Unknown",
    route_status: null,
    deviation_distance_m: null,
    gps: "UNAVAILABLE",
    gps_age_s: null,
    last_updated: null,
  }),
];

export function fleet(buses: FleetBus[] = FLEET_BUSES): AdminFleet {
  return {
    generated_at: "2026-10-05T02:10:00Z",
    sim_time: "2026-10-05T07:40:00+05:30",
    filters: { route_id: null, bus_id: null, status: null },
    total: buses.length,
    buses,
    options: {
      routes: ["R1", "R2", "R3", "R4", "R5"].map((r) => ({ value: r, label: `${r} · Route ${r}` })),
      buses: buses.map((b) => ({ value: b.bus_id, label: `Bus ${b.bus_id}` })),
      statuses: [
        ["active", "Active"],
        ["delayed", "Delayed"],
        ["deviated", "Deviated"],
        ["idle", "Idle"],
      ].map(([value, label]) => ({ value: value!, label: label! })),
    },
  };
}

export const OVERVIEW: AdminOverview = {
  generated_at: "2026-10-05T02:10:00Z",
  sim_time: "2026-10-05T07:40:00+05:30",
  service_date: "2026-10-05",
  simulation_paused: false,
  total_buses: 12,
  buses_in_service: 12,
  buses_on_trip: 5,
  active_trips: 5,
  trips_today: { total: 24, scheduled: 17, active: 5, completed: 2, cancelled: 0 },
  students: 300,
  assigned_students: 296,
  passengers_today: 187,
  passengers_method: "Sum of per-trip peak load",
  qr_boardings_today: 4,
  delayed_buses: 1,
  deviated_buses: 2,
  major_deviations: 1,
  alerts: { active: 3, unread: 3, critical: 1, warning: 2, info: 0 },
};

export function alert(type: string, message: string, over: Partial<AlertOut> = {}): AlertOut {
  const id = over.alert_id ?? `ALT-${type}-ADMIN-${over.bus_id ?? "B05"}-T1-1`;
  return {
    alert_id: id,
    id,
    type: type as AlertOut["type"],
    title: type.replace(/_/g, " "),
    message,
    body: message,
    bus_id: "B05",
    trip_id: "T1",
    route_id: "R3",
    student_id: null,
    admin_id: null,
    recipient: "admin",
    severity: "warning",
    timestamp: "2026-10-05T02:10:00Z",
    created_at: "2026-10-05T02:10:00Z",
    updated_at: null,
    read: false,
    resolved_at: null,
    active: true,
    payload: {},
    ...over,
  };
}

export const ALERTS: AlertOut[] = [
  alert("ROUTE_DEVIATION", "Bus 05 is 303 m off route", { severity: "critical" }),
  alert("CAPACITY_WARNING", "Bus 07 is 88% occupied", { bus_id: "B07", route_id: "R4" }),
  alert("BUS_DELAYED", "Bus 15 is 8 min delayed", { bus_id: "B15", route_id: "R2" }),
];

function adminRoute(
  id: string,
  name: string,
  color: string,
  over: Partial<AdminRoute> = {},
): AdminRoute {
  return {
    id,
    name,
    color,
    length_km: 18.4,
    directions: [
      {
        variant_id: id,
        direction: "to_campus",
        label: `${id} — To Campus`,
        stop_count: 3,
        first_stop: { id: "S01", name: "Tambaram Station" },
        last_stop: { id: "S99", name: "Campus" },
        scheduled_duration_min: 52,
      },
      {
        variant_id: `${id}-E`,
        direction: "from_campus",
        label: `${id} — From Campus`,
        stop_count: 3,
        first_stop: { id: "S99", name: "Campus" },
        last_stop: { id: "S01", name: "Tambaram Station" },
        scheduled_duration_min: 52,
      },
    ],
    assigned_buses: [],
    active_buses: [],
    trips_today: { total: 4, scheduled: 2, active: 1, completed: 1, cancelled: 0 },
    delayed_buses: [],
    deviated_buses: [],
    avg_occupancy_percentage: 62,
    passengers_today: 71,
    ...over,
  };
}

export const ROUTES: AdminRoute[] = [
  adminRoute("R1", "Tambaram", "#2563eb", { assigned_buses: ["B12"], active_buses: ["B12"] }),
  adminRoute("R2", "Velachery", "#d97706", {
    assigned_buses: ["B15"],
    active_buses: ["B15"],
    delayed_buses: ["B15"],
  }),
  adminRoute("R3", "Thiruvanmiyur – OMR", "#7c3aed", {
    assigned_buses: ["B05", "B06"],
    active_buses: ["B05", "B06"],
    deviated_buses: ["B05", "B06"],
  }),
];

export function routeDetail(id: string): RouteDetail {
  const stop = (stop_id: string, name: string, seq: number) => ({
    stop_id,
    name,
    location: { type: "Point" as const, coordinates: [80.1 + seq / 100, 12.9] as [number, number] },
    seq,
    distance_along_m: seq * 4000,
    scheduled_offset_s: seq * 600,
    dwell_s: 30,
  });
  return {
    id,
    name: `Route ${id}`,
    color: "#2563eb",
    length_m: 18400,
    path: {
      type: "LineString",
      coordinates: [
        [80.1, 12.9],
        [80.12, 12.92],
      ],
    },
    directions: [
      {
        variant_id: id,
        direction: "to_campus",
        label: `${id} — To Campus`,
        stops: [
          stop("S01", "Tambaram Station", 0),
          stop("S02", "Library Gate", 1),
          stop("S99", "Campus", 2),
        ],
      },
      {
        variant_id: `${id}-E`,
        direction: "from_campus",
        label: `${id} — From Campus`,
        stops: [
          stop("S99", "Campus", 0),
          stop("S02", "Library Gate", 1),
          stop("S01", "Tambaram Station", 2),
        ],
      },
    ],
  };
}

export const SCHEDULE: AdminSchedule = {
  service_date: "2026-10-05",
  generated_at: "2026-10-05T02:10:00Z",
  trips: [
    {
      trip_id: "T-20261005-R1-0715",
      route_id: "R1",
      route_name: "Tambaram",
      route_color: "#2563eb",
      route_direction_id: "R1",
      direction: "to_campus",
      direction_label: "R1 — To Campus",
      first_stop: "Tambaram Station",
      last_stop: "Campus",
      scheduled_departure: "2026-10-05T01:45:00Z",
      scheduled_arrival: "2026-10-05T02:37:00Z",
      actual_start: "2026-10-05T01:46:00Z",
      actual_end: null,
      bus_id: "B12",
      reg_no: "TN 00 CR 1012",
      driver: { id: "D12", name: "Ravi Shankar" },
      status: "active",
      delay_min: 2,
    },
    {
      trip_id: "T-20261005-R2-0730",
      route_id: "R2",
      route_name: "Velachery",
      route_color: "#d97706",
      route_direction_id: "R2-E",
      direction: "from_campus",
      direction_label: "R2 — From Campus",
      first_stop: "Campus",
      last_stop: "Velachery",
      scheduled_departure: "2026-10-05T11:00:00Z",
      scheduled_arrival: "2026-10-05T11:50:00Z",
      actual_start: null,
      actual_end: null,
      bus_id: "B15",
      reg_no: "TN 00 CR 1015",
      driver: { id: "D15", name: "Meena K" },
      status: "scheduled",
      delay_min: null,
    },
  ],
};

export const ANALYTICS: AdminAnalytics = {
  generated_at: "2026-10-05T02:10:00Z",
  service_date: "2026-10-05",
  live: {
    passengers_per_route: [
      { label: "R1", key: "R1", value: 71, color: "#2563eb" },
      { label: "R2", key: "R2", value: 54, color: "#d97706" },
    ],
    occupancy_by_bus: [
      {
        bus_id: "B15",
        route_id: "R2",
        occupancy: 41,
        capacity: 50,
        occupancy_percentage: 82,
        crowding: "High",
      },
    ],
    trips_today: { total: 24, scheduled: 17, active: 5, completed: 2, cancelled: 0 },
    trips_by_departure_hour: [
      { label: "07:00", value: 8, key: null, color: null },
      { label: "16:00", value: 8, key: null, color: null },
    ],
    average_delay: {
      buses_measured: 5,
      fleet_avg_delay_min: 2.4,
      by_route: [{ label: "R2", key: "R2", value: 8, color: "#d97706" }],
    },
    qr_boardings_by_slot: [],
  },
  synthetic: {
    synthetic: true,
    label: "Synthetic demo data",
    method: "Deterministic demo series",
    seed: 42,
    daily_passengers: [{ label: "Mon 28", key: "2026-09-28", value: 455, color: null }],
    average_delay_by_day: [{ label: "Mon 28", key: "2026-09-28", value: 3.1, color: null }],
    peak_boarding_by_hour: [
      { label: "07:00", value: 231, key: null, color: null },
      { label: "16:00", value: 160, key: null, color: null },
    ],
    passengers_per_route_weekly_avg: [{ label: "R1", key: "R1", value: 80, color: "#2563eb" }],
  },
};

export function routeStatus(over: Partial<RouteStatusResponse> = {}): RouteStatusResponse {
  return {
    bus_id: "B05",
    trip_id: "T-B05",
    route_id: "R3",
    route_direction_id: "R3",
    route_status: "MAJOR_DEVIATION",
    deviation_distance_m: 312.4,
    thresholds: { minor_m: 50, major_m: 150 },
    expected_route: {
      type: "LineString",
      coordinates: [
        [80.2, 12.9],
        [80.21, 12.91],
        [80.22, 12.92],
      ],
    },
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

export const TRIP_BOARDING: TripBoardingOut = {
  trip_id: "T-B05",
  bus_id: "B05",
  route_direction_id: "R3",
  total_boarded: 1,
  visibility: "all",
  events: [
    {
      boarding_id: "BRD-T-B05-U-S0001",
      student_id: "U-S0001",
      bus_id: "B05",
      trip_id: "T-B05",
      stop_id: "S27",
      timestamp: "2026-10-05T02:09:00Z",
      scanner: "simulated",
    },
  ],
};

export type Handler = (key: string, body: unknown) => Response | Promise<Response> | undefined;

export interface FakeBackend {
  fetchImpl: typeof fetch;
  calls: { key: string; body: unknown }[];
  count: (key: string) => number;
}

/** `GET /api/v1/x` style keys; `override` may answer any request first. */
export function fakeBackend(override?: Handler): FakeBackend {
  const calls: { key: string; body: unknown }[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const url = new URL(String(input));
    const key = `${init?.method ?? "GET"} ${url.pathname}${url.search}`;
    const body: unknown = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ key, body });
    const custom = await override?.(key, body);
    if (custom) return custom;
    const routeMatch = /^GET \/api\/v1\/routes\/(\w+)$/.exec(key);
    if (routeMatch) return json(routeDetail(routeMatch[1]!));
    switch (key) {
      case "POST /api/v1/auth/mock-login":
        return json({
          access_token: "mock.t",
          token_type: "bearer",
          expires_at: "2099-01-01T00:00:00Z",
        });
      case "GET /api/v1/me":
        return json({
          id: "U-A1",
          role: "admin",
          name: "Transport Office",
          email: "admin1@campusride.demo",
        });
      case "GET /api/v1/admin/overview":
        return json(OVERVIEW);
      case "GET /api/v1/admin/fleet":
        return json(fleet());
      case "GET /api/v1/admin/routes":
        return json(ROUTES);
      case "GET /api/v1/admin/schedule":
        return json(SCHEDULE);
      case "GET /api/v1/admin/analytics":
        return json(ANALYTICS);
      case "GET /api/v1/alerts?active=true":
        return json(ALERTS);
      case "GET /api/v1/alerts?active=false":
        return json([
          alert("BUS_DELAYED", "Bus 02 was 6 min late", {
            bus_id: "B02",
            active: false,
            read: true,
            resolved_at: "2026-10-05T02:05:00Z",
          }),
        ]);
      case "GET /api/v1/buses/B05/route-status":
        return json(routeStatus());
      case "GET /api/v1/trips/T-B05/boarding":
        return json(TRIP_BOARDING);
    }
    if (key.startsWith("PATCH /api/v1/alerts/")) return json({ ...ALERTS[0], read: true });
    if (key === "POST /api/v1/sim/route-deviation") {
      const mode = (body as { mode: string }).mode;
      return json({ enabled: true, route_deviation: mode === "normal" ? {} : { B05: mode } });
    }
    return json({ error: { code: "not_found", message: key } }, 404);
  };
  return { fetchImpl, calls, count: (k) => calls.filter((c) => c.key === k).length };
}
