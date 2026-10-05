/**
 * Small, deliberately FAKE response objects shaped exactly like the backend
 * contract (typed with the generated OpenAPI types). They are NOT copies of the
 * seed data — names and ids are invented so tests never pin the real network.
 */
import type {
  AuthConfig,
  CommuteHistoryOut,
  ArrivalOut,
  BusOptionOut,
  BusOptionsOut,
  CommuteDecisionOut,
  Alert,
  RecoveryOptionOut,
  RecoveryOut,
  BoardingScanOut,
  MyBoardingOut,
  OccupancyOut,
  EtaPredictionOut,
  MyArrivalsOut,
  BusLiveOut,
  BusOut,
  HealthOut,
  MyAssignmentOut,
  MyStopBusesOut,
  MeOut,
  RouteDetailOut,
  RouteSummaryOut,
  SimStatusOut,
  StopBusOut,
  StopOut,
  StopServiceOut,
  TokenOut,
} from "../api/types";

export const me: MeOut = {
  id: "U-T1",
  role: "student",
  name: "Test Student",
  email: "t1@example.test",
  active: true,
};

export const token: TokenOut = {
  access_token: "mock.test.token",
  token_type: "bearer",
  expires_at: "2099-01-01T00:00:00Z",
  auth_method: "dev",
  user: me,
};

export const devAuth: AuthConfig = {
  mode: "dev",
  development: true,
  dev_login: true,
  password_login: false,
  external_provider: false,
  oidc_issuer: null,
};

export const passwordAuth: AuthConfig = {
  ...devAuth,
  mode: "password",
  development: false,
  dev_login: false,
  password_login: true,
};

export const health: HealthOut = {
  status: "ok",
  app: "CampusRide",
  env: "test",
  db: "ok",
  clock: {
    mode: "sim",
    now: "2030-01-07T01:45:00Z",
    local_now: "2030-01-07T07:15:00+05:30",
    speed: 5,
    paused: true,
  },
};

const pt = (lng: number, lat: number) => ({
  type: "Point" as const,
  coordinates: [lng, lat] as [number, number],
});

export const stops: StopOut[] = [
  {
    id: "X0",
    name: "Test Campus",
    location: pt(10.0, 1.0),
    walk_radius_m: 600,
    is_campus_terminal: true,
  },
  {
    id: "X1",
    name: "Test Stop A",
    location: pt(10.1, 1.1),
    walk_radius_m: 400,
    is_campus_terminal: false,
  },
  {
    id: "X2",
    name: "Test Stop B",
    location: pt(10.2, 1.2),
    walk_radius_m: 400,
    is_campus_terminal: false,
  },
  {
    id: "X3",
    name: "Test Stop C",
    location: pt(10.3, 1.3),
    walk_radius_m: 400,
    is_campus_terminal: false,
  },
];

function detail(id: string, name: string, color: string, stopIds: string[]): RouteDetailOut {
  const byId = new Map(stops.map((s) => [s.id, s]));
  const mk = (ids: string[]) =>
    ids.map((sid, seq) => ({
      stop_id: sid,
      name: byId.get(sid)!.name,
      location: byId.get(sid)!.location,
      seq,
      distance_along_m: seq * 5000,
      scheduled_offset_s: seq * 300,
      dwell_s: 30,
    }));
  return {
    id,
    name,
    color,
    length_m: (stopIds.length - 1) * 1000,
    path: {
      type: "LineString",
      coordinates: stopIds.map((s) => byId.get(s)!.location.coordinates),
    },
    directions: [
      { variant_id: id, direction: "to_campus", label: `${id} — To Campus`, stops: mk(stopIds) },
      {
        variant_id: `${id}-E`,
        direction: "from_campus",
        label: `${id}-E — From Campus`,
        stops: mk([...stopIds].reverse()),
      },
    ],
  };
}

// X2 is shared by both test routes; X0 is the campus terminal.
export const routeDetails: RouteDetailOut[] = [
  detail("T1", "Test Line One", "#aa0000", ["X1", "X2", "X0"]),
  detail("T2", "Test Line Two", "#0000aa", ["X3", "X2", "X0"]),
];

export const routeSummaries: RouteSummaryOut[] = routeDetails.map((r) => ({
  id: r.id,
  name: r.name,
  color: r.color,
  length_m: r.length_m,
  directions: r.directions.map((d) => ({
    variant_id: d.variant_id,
    direction: d.direction,
    label: d.label,
    stop_count: d.stops.length,
    first_stop_id: d.stops[0]!.stop_id,
    last_stop_id: d.stops[d.stops.length - 1]!.stop_id,
  })),
}));

export function servicesAt(stopId: string): StopServiceOut[] {
  return routeDetails.flatMap((r) =>
    r.directions.flatMap((d) =>
      d.stops
        .filter((s) => s.stop_id === stopId)
        .map((s) => ({
          route_id: r.id,
          variant_id: d.variant_id,
          direction: d.direction,
          label: d.label,
          color: r.color,
          seq: s.seq,
          distance_along_m: s.distance_along_m,
          scheduled_offset_s: s.scheduled_offset_s,
        })),
    ),
  );
}

/** Fake college assignment: bus "BX7" on T2 To Campus, boarding at the shared stop X2. */
export const assignment: MyAssignmentOut = {
  student_id: me.id,
  status: "assigned",
  assignment: {
    bus: { id: "BX7", reg_no: "TEST 0007" },
    route: {
      route_id: "T2",
      route_direction_id: "T2",
      direction: "to_campus",
      label: "T2 — To Campus",
      name: "Test Line Two",
      color: "#0000aa",
    },
    boarding_stop: {
      stop_id: "X2",
      name: "Test Stop B",
      location: stops[2]!.location,
      seq: 1,
      stop_count: 3,
      scheduled_offset_s: 300,
    },
    assigned_at: "2030-01-01T00:00:00Z",
  },
};

export const unassigned: MyAssignmentOut = {
  student_id: me.id,
  status: "unassigned",
  assignment: null,
};

/** A backend-shaped `live` object (as tracking would derive it). */
export function live(
  routeDirectionId: string,
  distanceAlong: number,
  overrides: Partial<BusLiveOut> = {},
): BusLiveOut {
  const routeId = routeDirectionId.replace(/-E$/, "");
  const route = routeDetails.find((r) => r.id === routeId)!;
  const dir = route.directions.find((d) => d.variant_id === routeDirectionId)!;
  const after = dir.stops.filter((s) => s.distance_along_m <= distanceAlong);
  const next = dir.stops.find((s) => s.distance_along_m > distanceAlong);
  const frac = Math.min(1, distanceAlong / 10_000);
  const [a, b] = [
    route.path.coordinates[0]!,
    route.path.coordinates[route.path.coordinates.length - 1]!,
  ];
  return {
    trip_id: `T-TEST-${routeDirectionId}`,
    route_id: routeId,
    route_direction_id: routeDirectionId,
    direction: dir.direction,
    location: {
      type: "Point",
      coordinates: [a[0] + frac * (b[0] - a[0]), a[1] + frac * (b[1] - a[1])],
    },
    speed_mps: 8,
    heading_deg: 200,
    status: "en_route",
    schedule_status: "on_time",
    delay_s: 30,
    current_stop_id: after[after.length - 1]?.stop_id ?? null,
    next_stop_id: next?.stop_id ?? null,
    route_progress: frac,
    distance_along_m: distanceAlong,
    occupancy: 20,
    // as the BACKEND reports them (services/capacity.py) — never derived in the browser
    available_seats: 30,
    occupancy_percentage: 40,
    boarded_count: 0,
    route_status: "NORMAL",
    deviation_distance_m: 6.2,
    last_updated: "2030-01-07T01:50:00Z",
    stale: false,
    ...overrides,
  };
}

/**
 * Fake fleet: BX7 (the assigned bus) and BX9 run T2, BX8 runs T1 — both routes
 * serve the boarding stop X2 (at 5 km on each route, to campus).
 */
export const buses: BusOut[] = [
  {
    id: "BX7",
    reg_no: "TEST 0007",
    capacity: 50,
    route_id: "T2",
    status: "active",
    source: "sim",
    live: live("T2", 1800),
  },
  {
    id: "BX8",
    reg_no: "TEST 0008",
    capacity: 40,
    route_id: "T1",
    status: "active",
    source: "sim",
    live: live("T1", 4200, { occupancy: 37 }),
  },
  {
    id: "BX9",
    reg_no: "TEST 0009",
    capacity: 50,
    route_id: "T2",
    status: "active",
    source: "sim",
    live: live("T2", 0, { status: "at_depot", speed_mps: 0 }),
  },
];

export const simStatus: SimStatusOut = {
  enabled: true,
  running: true,
  paused: false,
  speed: 5,
  allowed_speeds: [1, 2, 5, 10, 20],
  sim_time: "2030-01-07T01:50:00Z",
  local_time: "2030-01-07T07:20:00+05:30",
  start_time: "2030-01-07T01:45:00Z",
  service_date: "2030-01-07",
  buses: 3,
  telemetry_interval_s: 5,
  controls_allowed: true,
  route_deviation: {},
};

/**
 * A FAKE backend matching result (`StopBusOut`) for a fleet bus relative to
 * `stopId` — hand-specified like the backend would return it. The frontend
 * never computes these values itself.
 */
export function stopBus(
  busId: string,
  match: Partial<NonNullable<StopBusOut["match"]>> | null,
  overrides: Partial<StopBusOut> = {},
): StopBusOut {
  const bus = buses.find((b) => b.id === busId)!;
  const l = bus.live!;
  const route = routeDetails.find((r) => r.id === l.route_id)!;
  const dir = route.directions.find((d) => d.variant_id === l.route_direction_id)!;
  const ref = (id: string | null) => {
    const s = dir.stops.find((x) => x.stop_id === id);
    return s ? { id: s.stop_id, name: s.name, seq: s.seq } : null;
  };
  const current = ref(l.current_stop_id)!;
  // what the backend's capacity rules would report for this fake bus
  const occupancy = overrides.occupancy ?? l.occupancy;
  return {
    bus_id: bus.id,
    bus_number: bus.id,
    reg_no: bus.reg_no,
    capacity: bus.capacity,
    route_id: route.id,
    route_direction_id: dir.variant_id,
    route_name: route.name,
    direction: dir.direction,
    direction_label: dir.label,
    status: l.status,
    schedule_status: l.schedule_status,
    delay_s: l.delay_s,
    location: l.location,
    speed_mps: l.speed_mps,
    heading_deg: l.heading_deg,
    route_progress: l.route_progress,
    occupancy,
    available_seats: Math.max(bus.capacity - occupancy, 0),
    occupancy_percentage: Math.round((100 * occupancy) / bus.capacity),
    last_updated: l.last_updated,
    stale: false,
    route_status: l.route_status,
    deviation_distance_m: l.deviation_distance_m,
    position: {
      current_stop: current,
      previous_stop: current.seq > 0 ? ref(dir.stops[current.seq - 1]!.stop_id) : null,
      next_stop: ref(l.next_stop_id),
      at_stop: l.status === "dwelling" || l.status === "at_depot",
      distance_to_next_stop_m: 1000,
    },
    match:
      match === null
        ? null
        : {
            stop_id: "X2",
            proximity: "far_from_stop",
            position: "ahead",
            distance_to_stop_m: 3200,
            stop_offset_m: 3200,
            stops_away: 1,
            progress_to_stop: 0.36,
            dwelling_at_stop: false,
            ...match,
          },
    is_assigned_bus: busId === "BX7",
    ...overrides,
  };
}

/** Fake `GET /students/me/stop/buses`: BX7 is mine; BX8 (T1) and BX9 (T2) also serve X2 to campus. */
export const myStopBuses: MyStopBusesOut = {
  student_id: me.id,
  status: "assigned",
  boarding_stop: { id: "X2", name: "Test Stop B" },
  assigned_bus_id: "BX7",
  route_direction_id: "T2",
  direction: "to_campus",
  my_bus: stopBus("BX7", { distance_to_stop_m: 3200, stop_offset_m: 3200, stops_away: 1 }),
  my_bus_serving_stop: true,
  other_buses: [
    stopBus("BX8", {
      proximity: "approaching_stop",
      distance_to_stop_m: 800,
      stop_offset_m: 800,
      stops_away: 1,
    }),
    stopBus("BX9", { distance_to_stop_m: 5000, stop_offset_m: 5000, stops_away: 1 }),
  ],
};

export const myStopUnassigned: MyStopBusesOut = {
  student_id: me.id,
  status: "unassigned",
  boarding_stop: null,
  assigned_bus_id: null,
  route_direction_id: null,
  direction: null,
  my_bus: null,
  my_bus_serving_stop: false,
  other_buses: [],
};

export const COMPUTED_AT = "2030-01-07T01:50:00Z"; // sim time of the fake predictions

/** A FAKE backend ETA prediction (as `EtaPredictionOut`); minutes are whole. */
export function eta(
  minutes: number | null,
  over: Partial<EtaPredictionOut> = {},
): EtaPredictionOut {
  const secs = minutes === null ? null : minutes * 60;
  return {
    status: minutes === null ? "passed" : "predicted",
    eta_minutes: minutes,
    eta_seconds: secs,
    estimated_arrival_time:
      secs === null ? null : new Date(Date.parse(COMPUTED_AT) + secs * 1000).toISOString(),
    computed_at: COMPUTED_AT,
    confidence: "high",
    traffic: "Moderate",
    traffic_factor: 1.36,
    delay_factor: 1.0,
    breakdown: {
      travel_s: secs ?? 0,
      dwell_s: 0,
      wait_s: 0,
      timetable_s: secs,
      history_source: "timetable",
    },
    ...over,
  };
}

export function arrival(
  busId: string,
  match: Parameters<typeof stopBus>[1],
  prediction: EtaPredictionOut,
  overrides: Partial<StopBusOut> = {},
): ArrivalOut {
  return { ...stopBus(busId, match, overrides), eta: prediction };
}

/** Fake `GET /students/me/arrivals`, ordered by backend ETA: BX8 (2 min), BX7 = mine (7), BX9 (14). */
export const myArrivals: MyArrivalsOut = {
  student_id: me.id,
  status: "assigned",
  boarding_stop: { id: "X2", name: "Test Stop B" },
  assigned_bus_id: "BX7",
  route_direction_id: "T2",
  direction: "to_campus",
  my_bus: arrival("BX7", { distance_to_stop_m: 3200, stop_offset_m: 3200, stops_away: 1 }, eta(7)),
  my_bus_serving_stop: true,
  arrivals: [
    arrival(
      "BX8",
      { proximity: "approaching_stop", distance_to_stop_m: 800, stop_offset_m: 800, stops_away: 1 },
      eta(2, { traffic: "Low", confidence: "medium" }),
    ),
    arrival("BX7", { distance_to_stop_m: 3200, stop_offset_m: 3200, stops_away: 1 }, eta(7)),
    arrival(
      "BX9",
      { distance_to_stop_m: 5000, stop_offset_m: 5000, stops_away: 1 },
      eta(14, { confidence: "low" }),
    ),
  ],
};

export const myArrivalsUnassigned: MyArrivalsOut = {
  student_id: me.id,
  status: "unassigned",
  boarding_stop: null,
  assigned_bus_id: null,
  route_direction_id: null,
  direction: null,
  my_bus: null,
  my_bus_serving_stop: false,
  arrivals: [],
};

/** A FAKE backend comparison option: an arrival + the backend's comparison fields. */
export function option(a: ArrivalOut, over: Partial<BusOptionOut> = {}): BusOptionOut {
  return {
    ...a,
    occupancy_percentage: Math.round((100 * a.occupancy) / a.capacity),
    seats_available: Math.max(a.capacity - a.occupancy, 0),
    crowding: "Low",
    delay_minutes: Math.round(a.delay_s / 60),
    comparable: true,
    indicators: [],
    trade_off: null,
    ...over,
  };
}

/**
 * Fake `GET /students/me/bus-options` — the trade-off the backend decided:
 * BX8 is soonest but crowded, my BX7 is the best alternative, BX9 is emptiest.
 */
export const myBusOptions: BusOptionsOut = {
  student_id: me.id,
  status: "assigned",
  boarding_stop: { id: "X2", name: "Test Stop B" },
  assigned_bus_id: "BX7",
  route_direction_id: "T2",
  direction: "to_campus",
  assigned_bus_available: true,
  assigned_bus_note: null,
  computed_at: COMPUTED_AT,
  options: [
    option(myArrivals.arrivals[0]!, {
      occupancy: 46,
      capacity: 50,
      delay_minutes: 0,
      occupancy_percentage: 92,
      seats_available: 4,
      crowding: "High",
      indicators: ["FASTEST"],
    }),
    option(
      { ...myArrivals.arrivals[1]!, is_assigned_bus: true, delay_s: 120 },
      {
        occupancy: 24,
        occupancy_percentage: 48,
        seats_available: 26,
        crowding: "Low",
        delay_minutes: 2,
        indicators: ["ASSIGNED", "BEST_ALTERNATIVE"],
        trade_off: "+5 min vs BX8 · 22 more seats free",
      },
    ),
    option(myArrivals.arrivals[2]!, {
      occupancy: 9,
      occupancy_percentage: 18,
      seats_available: 41,
      crowding: "Low",
      indicators: ["LEAST_CROWDED"],
      trade_off: "+12 min vs BX8 · 37 more seats free",
    }),
  ],
  excluded: [{ bus_id: "BX6", bus_number: "BX6", reason: "passed_stop" }],
};

export const myBusOptionsUnassigned: BusOptionsOut = {
  student_id: me.id,
  status: "unassigned",
  boarding_stop: null,
  assigned_bus_id: null,
  route_direction_id: null,
  direction: null,
  assigned_bus_available: false,
  assigned_bus_note: null,
  computed_at: null,
  options: [],
  excluded: [],
};

/**
 * A FAKE backend commute decision for the assigned bus BX7 (`GET /students/me/commute-decision`).
 * Default: YES — bus in 7 min, 4 min walk, 2 min buffer.
 */
export function commute(over: Partial<CommuteDecisionOut> = {}): CommuteDecisionOut {
  const prediction = eta(7);
  return {
    student_id: me.id,
    status: "assigned",
    decision: "YES",
    reason: "You should reach your stop before the bus.",
    bus_id: "BX7",
    bus_number: "BX7",
    route_direction_id: "T2",
    boarding_stop: { id: "X2", name: "Test Stop B" },
    student_location: {
      location: { type: "Point", coordinates: [80.21, 12.91] },
      source: "synthetic",
      label: "Simulated location (demo, not GPS)",
    },
    walking_distance_m: 340,
    walking_speed_mps: 1.4,
    walking_time_minutes: 4,
    bus_eta_minutes: 7,
    bus_arrival_time: prediction.estimated_arrival_time,
    required_arrival_time: new Date(Date.parse(COMPUTED_AT) + 300_000).toISOString(),
    student_arrival_time: new Date(Date.parse(COMPUTED_AT) + 240_000).toISOString(),
    safety_buffer_minutes: 2,
    spare_minutes: 3,
    delay_minutes: 0,
    bus_status: "en_route",
    proximity: "far_from_stop",
    stale: false,
    eta: prediction,
    alternatives_available: 2,
    computed_at: COMPUTED_AT,
    ...over,
  };
}

export const myCommute: CommuteDecisionOut = commute();

export const myCommuteUnassigned: CommuteDecisionOut = commute({
  status: "unassigned",
  decision: null,
  reason: "Your bus assignment is not available yet.",
  bus_id: null,
  bus_number: null,
  route_direction_id: null,
  boarding_stop: null,
  student_location: null,
  walking_distance_m: null,
  walking_speed_mps: null,
  walking_time_minutes: null,
  bus_eta_minutes: null,
  bus_arrival_time: null,
  required_arrival_time: null,
  student_arrival_time: null,
  spare_minutes: null,
  delay_minutes: null,
  bus_status: null,
  proximity: null,
  eta: null,
  alternatives_available: 0,
});

/** Fake backend occupancy for the assigned bus BX7 (38 / 50 → 76 %, 12 seats). */
export function occupancy(over: Partial<OccupancyOut> = {}): OccupancyOut {
  return {
    bus_id: "BX7",
    trip_id: "T-TEST-T2",
    occupancy: 38,
    capacity: 50,
    available_seats: 12,
    occupancy_percentage: 76,
    baseline: 38,
    boarded: 0,
    source: "synthetic_baseline+qr",
    updated_at: "2030-01-07T01:50:00Z",
    ...over,
  };
}

/** Fake `GET /students/me/boarding`: assigned BX7, trip running, ready to scan. */
export const myBoarding: MyBoardingOut = {
  student_id: me.id,
  status: "assigned",
  bus_id: "BX7",
  bus_number: "BX7",
  route_direction_id: "T2",
  boarding_stop: { id: "X2", name: "Test Stop B" },
  trip_id: "T-TEST-T2",
  ready: true,
  reason_code: null,
  reason: null,
  boarded: null,
  occupancy: occupancy(),
};

/** Fake `POST /boarding/scan` result (the backend's numbers after one boarding). */
export function scanResult(over: Partial<BoardingScanOut> = {}): BoardingScanOut {
  return {
    ...occupancy({ occupancy: 39, available_seats: 11, occupancy_percentage: 78, boarded: 1 }),
    status: "boarded",
    boarding_id: "BRD-T-TEST-T2-" + me.id,
    student_id: me.id,
    stop_id: "X2",
    timestamp: "2030-01-07T01:50:00Z",
    message: "Boarding recorded.",
    ...over,
  };
}

/** A FAKE backend recovery option (as `GET /students/me/recovery-options` returns it). */
export function recoveryOption(
  busId: string,
  over: Partial<RecoveryOptionOut> = {},
): RecoveryOptionOut {
  const minutes = over.eta_minutes ?? 9;
  const prediction = eta(minutes);
  return {
    bus_id: busId,
    bus_number: busId,
    trip_id: `T-TEST-${busId}`,
    route_id: "T1",
    route_direction_id: "T1",
    route_name: "Test Line One",
    direction: "to_campus",
    boarding_stop_id: "X2",
    boarding_stop_name: "Test Stop B",
    eta_minutes: minutes,
    estimated_arrival_time: prediction.estimated_arrival_time,
    eta: prediction,
    occupancy: 24,
    capacity: 50,
    available_seats: 26,
    occupancy_percentage: 48,
    status: "on_time",
    bus_status: "en_route",
    delay_minutes: 0,
    distance_to_stop_m: 1200,
    stops_away: 2,
    catchable: true,
    safety_buffer_minutes: 5,
    walking_time_minutes: 4,
    reason: `Bus ${busId} serves your stop and gives you a 5-minute safety buffer.`,
    ...over,
  };
}

/** Fake recovery: my BX7 is at risk; the backend recommends BX8, then BX9. */
export function recovery(over: Partial<RecoveryOut> = {}): RecoveryOut {
  return {
    student_id: me.id,
    status: "recovery_available",
    trigger: "likely_to_miss",
    commute_decision: "RISK",
    assigned_bus_id: "BX7",
    assigned_bus: "BUS BX7",
    assigned_bus_delay_minutes: 0,
    boarding_stop_id: "X2",
    boarding_stop_name: "Test Stop B",
    route_direction_id: "T2",
    required_buffer_minutes: 2,
    recommended: recoveryOption("BX8"),
    alternatives: [
      recoveryOption("BX9", {
        eta_minutes: 14,
        occupancy: 10,
        available_seats: 40,
        occupancy_percentage: 20,
        safety_buffer_minutes: 10,
        reason:
          "Bus BX9 is less crowded and still gives you enough time to reach the stop (10 min to spare).",
      }),
    ],
    excluded: [],
    computed_at: COMPUTED_AT,
    ...over,
  };
}

/** The usual case: assigned bus comfortably catchable → nothing to show. */
export const recoveryNotNeeded: RecoveryOut = recovery({
  status: "not_needed",
  trigger: null,
  commute_decision: "YES",
  recommended: null,
  alternatives: [],
});

/** A FAKE backend alert (as `GET /alerts` returns it for the signed-in student). */
export function alert(type: Alert["type"], message: string, over: Partial<Alert> = {}): Alert {
  const titles: Record<string, string> = {
    BUS_APPROACHING: "BUS APPROACHING",
    BUS_DELAYED: "BUS DELAYED",
    CAPACITY_WARNING: "CAPACITY WARNING",
    ROUTE_DEVIATION: "ROUTE DEVIATION",
    MISSED_BUS: "MISSED BUS",
    ALTERNATIVE_BUS_AVAILABLE: "ALTERNATIVE AVAILABLE",
  };
  const id = over.alert_id ?? `ALT-${type}-S-${me.id}-BX7-T-TEST-T2-1`;
  const ts = over.timestamp ?? "2030-01-07T01:46:00Z";
  return {
    alert_id: id,
    id,
    type,
    title: titles[type] ?? type,
    message,
    body: message,
    bus_id: "BX7",
    trip_id: "T-TEST-T2",
    route_id: "T2",
    student_id: me.id,
    admin_id: null,
    recipient: "student",
    severity: "info",
    timestamp: ts,
    created_at: ts,
    updated_at: null,
    read: false,
    resolved_at: null,
    active: true,
    payload: {},
    ...over,
  };
}

/** Fake `GET /alerts`: three of the student's own alerts, newest first (2 unread). */
export const myAlerts: Alert[] = [
  alert("BUS_APPROACHING", "Bus BX7 reaches your stop (Test Stop B) in 3 minutes.", {
    timestamp: "2030-01-07T01:48:00Z",
  }),
  alert("BUS_DELAYED", "Bus BX7 is running 8 minutes late.", {
    alert_id: "ALT-BUS_DELAYED-S-U-T1-BX7-T-TEST-T2-1",
    severity: "warning",
    timestamp: "2030-01-07T01:42:00Z",
  }),
  alert(
    "ALTERNATIVE_BUS_AVAILABLE",
    "Bus BX8 serves your stop and gives you a 5-minute safety buffer.",
    {
      alert_id: "ALT-ALTERNATIVE_BUS_AVAILABLE-S-U-T1-BX7-T-TEST-T2-1",
      bus_id: "BX8",
      read: true,
      timestamp: "2030-01-07T01:38:00Z",
    },
  ),
];

// ---- Feature 16 — student commute experience

export const myHistory: CommuteHistoryOut = {
  student_id: me.id,
  generated_at: "2030-01-07T02:30:00Z",
  entries: [
    {
      trip_id: "T-TEST-T2-0715",
      service_date: "2030-01-07",
      bus_id: "BX7",
      route_id: "T2",
      route_name: "Test Route Two",
      route_direction_id: "T2",
      direction: "to_campus",
      direction_label: "T2 — To Campus",
      boarding_stop: { id: "X2", name: "Test Stop B" },
      scheduled_departure: "2030-01-07T01:45:00Z",
      actual_start: "2030-01-07T01:46:00Z",
      actual_end: "2030-01-07T02:35:00Z",
      trip_status: "completed",
      end_reason: "terminal",
      outcome: "boarded",
      boarded: true,
      boarding_time: "2030-01-07T02:01:00Z",
      boarding_source: "qr",
      scanner: "simulated",
    },
    {
      trip_id: "T-TEST-T2-0715-PREV",
      service_date: "2030-01-06",
      bus_id: "BX7",
      route_id: "T2",
      route_name: "Test Route Two",
      route_direction_id: "T2",
      direction: "to_campus",
      direction_label: "T2 — To Campus",
      boarding_stop: { id: "X2", name: "Test Stop B" },
      scheduled_departure: "2030-01-06T01:45:00Z",
      actual_start: "2030-01-06T01:46:00Z",
      actual_end: "2030-01-06T02:10:00Z",
      trip_status: "completed",
      end_reason: "driver_stop",
      outcome: "ended_early",
      boarded: false,
      boarding_time: null,
      boarding_source: null,
      scanner: null,
    },
  ],
};
