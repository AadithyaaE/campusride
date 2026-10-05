/**
 * Lightweight runtime checks for backend responses.
 *
 * TypeScript types come from the OpenAPI schema, but a response is only
 * trusted at runtime after it passes these guards. They check the fields the
 * UI relies on, so a mismatched backend fails loudly with a clear error
 * instead of rendering `undefined` deep inside a component.
 */
import type {
  ArrivalOut,
  AuthConfig,
  CommuteHistoryEntry,
  CommuteHistoryOut,
  StudentCommuteOut,
  AssignmentOut,
  BusEtaOut,
  BusOptionOut,
  BusOptionsOut,
  CommuteDecisionOut,
  BoardingEventOut,
  BoardingScanOut,
  MyBoardingOut,
  OccupancyOut,
  TripBoardingOut,
  RecoveryOptionOut,
  RecoveryOut,
  RouteStatusResponse,
  Alert,
  EtaPredictionOut,
  MyArrivalsOut,
  StopArrivalsOut,
  BusDetailOut,
  BusOut,
  GeoPoint,
  HealthOut,
  LineString,
  MeOut,
  MyAssignmentOut,
  MyStopBusesOut,
  NearbyStopOut,
  RouteDetailOut,
  RouteSummaryOut,
  SimStatusOut,
  StopBusesOut,
  StopBusOut,
  StopOut,
  StopServiceOut,
  TokenOut,
} from "./types";

export type Guard<T> = (value: unknown) => value is T;

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isBool = (v: unknown): v is boolean => typeof v === "boolean";

const isLngLat = (v: unknown): boolean =>
  Array.isArray(v) && v.length === 2 && isNum(v[0]) && isNum(v[1]) && Math.abs(v[1]) <= 90;

const isDirection = (v: unknown) => v === "to_campus" || v === "from_campus";

export const arrayOf =
  <T>(guard: Guard<T>): Guard<T[]> =>
  (v: unknown): v is T[] =>
    Array.isArray(v) && v.every(guard);

export const isGeoPoint: Guard<GeoPoint> = (v): v is GeoPoint =>
  isObj(v) && v.type === "Point" && isLngLat(v.coordinates);

export const isLineString: Guard<LineString> = (v): v is LineString =>
  isObj(v) &&
  v.type === "LineString" &&
  Array.isArray(v.coordinates) &&
  v.coordinates.length >= 2 &&
  v.coordinates.every(isLngLat);

export const isHealth: Guard<HealthOut> = (v): v is HealthOut =>
  isObj(v) && isStr(v.status) && isStr(v.db) && isObj(v.clock) && isStr(v.clock.local_now);

export const isMe: Guard<MeOut> = (v): v is MeOut =>
  isObj(v) && isStr(v.id) && isStr(v.role) && isStr(v.name) && isStr(v.email);

export const isAuthConfig: Guard<AuthConfig> = (v): v is AuthConfig =>
  isObj(v) && isStr(v.mode) && isBool(v.development) && isBool(v.password_login);

export const isToken: Guard<TokenOut> = (v): v is TokenOut =>
  isObj(v) && isStr(v.access_token) && isStr(v.expires_at) && isMe(v.user);

export const isStop: Guard<StopOut> = (v): v is StopOut =>
  isObj(v) &&
  isStr(v.id) &&
  isStr(v.name) &&
  isGeoPoint(v.location) &&
  isBool(v.is_campus_terminal);

export const isNearbyStop: Guard<NearbyStopOut> = (v): v is NearbyStopOut =>
  isStop(v) && isNum((v as Obj).distance_m);

export const isStopService: Guard<StopServiceOut> = (v): v is StopServiceOut =>
  isObj(v) &&
  isStr(v.route_id) &&
  isStr(v.variant_id) &&
  isDirection(v.direction) &&
  isStr(v.label) &&
  isStr(v.color) &&
  isNum(v.seq) &&
  isNum(v.scheduled_offset_s);

export const isRouteSummary: Guard<RouteSummaryOut> = (v): v is RouteSummaryOut =>
  isObj(v) &&
  isStr(v.id) &&
  isStr(v.name) &&
  isStr(v.color) &&
  isNum(v.length_m) &&
  Array.isArray(v.directions) &&
  v.directions.every(
    (d) => isObj(d) && isStr(d.variant_id) && isDirection(d.direction) && isNum(d.stop_count),
  );

export const isRouteDetail: Guard<RouteDetailOut> = (v): v is RouteDetailOut =>
  isObj(v) &&
  isStr(v.id) &&
  isStr(v.name) &&
  isStr(v.color) &&
  isLineString(v.path) &&
  Array.isArray(v.directions) &&
  v.directions.every(
    (d) =>
      isObj(d) &&
      isStr(d.variant_id) &&
      isDirection(d.direction) &&
      isStr(d.label) &&
      Array.isArray(d.stops) &&
      d.stops.every(
        (s) =>
          isObj(s) && isStr(s.stop_id) && isStr(s.name) && isGeoPoint(s.location) && isNum(s.seq),
      ),
  );

const isAssignment = (v: unknown): v is AssignmentOut =>
  isObj(v) &&
  isObj(v.bus) &&
  isStr(v.bus.id) &&
  isObj(v.route) &&
  isStr(v.route.route_id) &&
  isStr(v.route.route_direction_id) &&
  isDirection(v.route.direction) &&
  isStr(v.route.color) &&
  isObj(v.boarding_stop) &&
  isStr(v.boarding_stop.stop_id) &&
  isStr(v.boarding_stop.name) &&
  isGeoPoint(v.boarding_stop.location) &&
  isNum(v.boarding_stop.seq) &&
  isNum(v.boarding_stop.stop_count);

/** Assigned ⇔ assignment present; anything else is a contract violation. */
export const isMyAssignment: Guard<MyAssignmentOut> = (v): v is MyAssignmentOut =>
  isObj(v) &&
  isStr(v.student_id) &&
  ((v.status === "assigned" && isAssignment(v.assignment)) ||
    (v.status === "unassigned" && v.assignment === null));

const isLive = (v: unknown): boolean =>
  v === null ||
  (isObj(v) &&
    isGeoPoint(v.location) &&
    isStr(v.status) &&
    isNum(v.speed_mps) &&
    isNum(v.route_progress) &&
    isNum(v.occupancy) &&
    isNum(v.distance_along_m) &&
    isStr(v.last_updated));

export const isBus: Guard<BusOut> = (v): v is BusOut =>
  isObj(v) &&
  isStr(v.id) &&
  isStr(v.reg_no) &&
  isNum(v.capacity) &&
  isStr(v.route_id) &&
  isStr(v.status) &&
  isLive(v.live);

export const isBusDetail: Guard<BusDetailOut> = (v): v is BusDetailOut =>
  isBus(v) && isObj(v) && "current_stop" in v && "next_stop" in v;

export const isSimStatus: Guard<SimStatusOut> = (v): v is SimStatusOut =>
  isObj(v) &&
  typeof v.enabled === "boolean" &&
  typeof v.paused === "boolean" &&
  isNum(v.speed) &&
  Array.isArray(v.allowed_speeds) &&
  typeof v.controls_allowed === "boolean";

const PROXIMITIES = ["far_from_stop", "approaching_stop", "at_stop", "passed_stop"];

export const isStopBus: Guard<StopBusOut> = (v): v is StopBusOut =>
  isObj(v) &&
  isStr(v.bus_id) &&
  isStr(v.route_direction_id) &&
  isDirection(v.direction) &&
  isStr(v.status) &&
  isNum(v.capacity) &&
  isNum(v.occupancy) &&
  isGeoPoint(v.location) &&
  isObj(v.position) &&
  isObj(v.position.current_stop) &&
  isStr(v.position.current_stop.id) &&
  (v.match === null ||
    (isObj(v.match) && isStr(v.match.stop_id) && PROXIMITIES.includes(String(v.match.proximity))));

export const isStopBuses: Guard<StopBusesOut> = (v): v is StopBusesOut =>
  isObj(v) && isObj(v.stop) && isStr(v.stop.id) && arrayOf(isStopBus)(v.buses);

/** Assigned ⇔ boarding stop + assigned bus present; unassigned ⇔ nothing invented. */
export const isMyStopBuses: Guard<MyStopBusesOut> = (v): v is MyStopBusesOut =>
  isObj(v) &&
  isStr(v.student_id) &&
  arrayOf(isStopBus)(v.other_buses) &&
  (v.my_bus === null || isStopBus(v.my_bus)) &&
  ((v.status === "assigned" && isObj(v.boarding_stop) && isStr(v.assigned_bus_id)) ||
    (v.status === "unassigned" &&
      v.boarding_stop === null &&
      v.my_bus === null &&
      v.other_buses.length === 0));

const ETA_STATUSES = ["predicted", "at_stop", "passed", "completed"];
const isIntOrNull = (v: unknown) => v === null || (isNum(v) && Number.isInteger(v));

export const isEta: Guard<EtaPredictionOut> = (v): v is EtaPredictionOut =>
  isObj(v) &&
  ETA_STATUSES.includes(String(v.status)) &&
  isIntOrNull(v.eta_minutes) &&
  isIntOrNull(v.eta_seconds) &&
  isStr(v.computed_at) &&
  (v.estimated_arrival_time === null || isStr(v.estimated_arrival_time)) &&
  ["high", "medium", "low"].includes(String(v.confidence)) &&
  ["Low", "Moderate", "High"].includes(String(v.traffic)) &&
  isNum(v.traffic_factor) &&
  isNum(v.delay_factor) &&
  (v.status !== "predicted" || (isNum(v.eta_minutes) && isStr(v.estimated_arrival_time)));

export const isArrival: Guard<ArrivalOut> = (v): v is ArrivalOut =>
  isStopBus(v) && isEta((v as Record<string, unknown>).eta);

export const isStopArrivals: Guard<StopArrivalsOut> = (v): v is StopArrivalsOut =>
  isObj(v) && isObj(v.stop) && isStr(v.stop.id) && arrayOf(isArrival)(v.arrivals);

export const isMyArrivals: Guard<MyArrivalsOut> = (v): v is MyArrivalsOut =>
  isObj(v) &&
  isStr(v.student_id) &&
  arrayOf(isArrival)(v.arrivals) &&
  (v.my_bus === null || isStopBus(v.my_bus)) &&
  ((v.status === "assigned" && isObj(v.boarding_stop) && isStr(v.assigned_bus_id)) ||
    (v.status === "unassigned" &&
      v.boarding_stop === null &&
      v.my_bus === null &&
      v.arrivals.length === 0));

export const isBusEta: Guard<BusEtaOut> = (v): v is BusEtaOut =>
  isEta(v) &&
  isStr((v as Obj).bus_id) &&
  isStr((v as Obj).stop_id) &&
  isStr((v as Obj).route_direction_id);

const INDICATORS = ["ASSIGNED", "FASTEST", "LEAST_CROWDED", "BEST_ALTERNATIVE"];

export const isBusOption: Guard<BusOptionOut> = (v): v is BusOptionOut =>
  isArrival(v) &&
  isIntOrNull((v as Obj).occupancy_percentage) &&
  isNum((v as Obj).seats_available) &&
  ["Low", "Medium", "High", "Unknown"].includes(String((v as Obj).crowding)) &&
  isIntOrNull((v as Obj).delay_minutes) &&
  isBool((v as Obj).comparable) &&
  Array.isArray((v as Obj).indicators) &&
  ((v as Obj).indicators as unknown[]).every((i) => INDICATORS.includes(String(i))) &&
  ((v as Obj).trade_off === null || isStr((v as Obj).trade_off));

export const isBusOptions: Guard<BusOptionsOut> = (v): v is BusOptionsOut =>
  isObj(v) &&
  isStr(v.student_id) &&
  isBool(v.assigned_bus_available) &&
  arrayOf(isBusOption)(v.options) &&
  Array.isArray(v.excluded) &&
  ((v.status === "assigned" && isObj(v.boarding_stop) && isStr(v.assigned_bus_id)) ||
    (v.status === "unassigned" && v.boarding_stop === null && v.options.length === 0));

const DECISIONS = ["YES", "RISK", "MISSED", "LOCATION_UNAVAILABLE", "UNKNOWN"];
const isStrOrNull = (v: unknown) => v === null || isStr(v);

export const isCommuteDecision: Guard<CommuteDecisionOut> = (v): v is CommuteDecisionOut =>
  isObj(v) &&
  isStr(v.student_id) &&
  isIntOrNull(v.walking_time_minutes) &&
  isIntOrNull(v.bus_eta_minutes) &&
  isIntOrNull(v.walking_distance_m) &&
  isIntOrNull(v.spare_minutes) &&
  isNum(v.safety_buffer_minutes) &&
  Number.isInteger(v.safety_buffer_minutes) &&
  isStrOrNull(v.bus_arrival_time) &&
  isStrOrNull(v.required_arrival_time) &&
  isBool(v.stale) &&
  (v.eta === null || isEta(v.eta)) &&
  (v.student_location === null ||
    (isObj(v.student_location) && v.student_location.source === "synthetic")) &&
  ((v.status === "assigned" && DECISIONS.includes(String(v.decision)) && isStr(v.reason)) ||
    (v.status === "unassigned" && v.decision === null));

const isInt = (v: unknown): v is number => isNum(v) && Number.isInteger(v);
const OCC_SOURCES = ["synthetic_baseline+qr", "qr", "no_live_data"];

export const isOccupancy: Guard<OccupancyOut> = (v): v is OccupancyOut =>
  isObj(v) &&
  isStr(v.bus_id) &&
  (v.trip_id === null || isStr(v.trip_id)) &&
  isInt(v.occupancy) &&
  isInt(v.capacity) &&
  isInt(v.available_seats) &&
  isIntOrNull(v.occupancy_percentage) &&
  isInt(v.boarded) &&
  OCC_SOURCES.includes(String(v.source));

export const isBoardingEvent: Guard<BoardingEventOut> = (v): v is BoardingEventOut =>
  isObj(v) &&
  isStr(v.boarding_id) &&
  isStr(v.bus_id) &&
  isStr(v.trip_id) &&
  isStr(v.stop_id) &&
  isStr(v.timestamp);

export const isBoardingScan: Guard<BoardingScanOut> = (v): v is BoardingScanOut =>
  isOccupancy(v) &&
  ["boarded", "already_boarded"].includes(String((v as Obj).status)) &&
  isStr((v as Obj).boarding_id) &&
  isStr((v as Obj).message);

export const isTripBoarding: Guard<TripBoardingOut> = (v): v is TripBoardingOut =>
  isObj(v) &&
  isStr(v.trip_id) &&
  isInt(v.total_boarded) &&
  ["all", "own", "count_only"].includes(String(v.visibility)) &&
  arrayOf(isBoardingEvent)(v.events);

export const isMyBoarding: Guard<MyBoardingOut> = (v): v is MyBoardingOut =>
  isObj(v) &&
  isStr(v.student_id) &&
  isBool(v.ready) &&
  (v.boarded === null || isBoardingEvent(v.boarded)) &&
  (v.occupancy === null || isOccupancy(v.occupancy)) &&
  ((v.status === "assigned" && isStr(v.bus_id) && isObj(v.boarding_stop)) ||
    (v.status === "unassigned" && v.bus_id === null && v.trip_id === null));

const RECOVERY_STATUSES = ["recovery_available", "not_needed", "no_alternative", "unassigned"];
const TRIGGERS = ["missed", "likely_to_miss", "significantly_delayed"];

export const isRecoveryOption: Guard<RecoveryOptionOut> = (v): v is RecoveryOptionOut =>
  isObj(v) &&
  isStr(v.bus_id) &&
  isStr(v.boarding_stop_id) &&
  isIntOrNull(v.eta_minutes) &&
  isEta(v.eta) &&
  isInt(v.occupancy) &&
  isInt(v.capacity) &&
  isInt(v.available_seats) &&
  isIntOrNull(v.occupancy_percentage) &&
  (v.status === "on_time" || v.status === "delayed") &&
  isInt(v.delay_minutes) &&
  (v.catchable === null || isBool(v.catchable)) &&
  isIntOrNull(v.safety_buffer_minutes) &&
  isStr(v.reason);

export const isRecovery: Guard<RecoveryOut> = (v): v is RecoveryOut =>
  isObj(v) &&
  isStr(v.student_id) &&
  RECOVERY_STATUSES.includes(String(v.status)) &&
  (v.trigger === null || TRIGGERS.includes(String(v.trigger))) &&
  (v.recommended === null || isRecoveryOption(v.recommended)) &&
  arrayOf(isRecoveryOption)(v.alternatives) &&
  // never an option without a recommendation, never a recommendation without a trigger
  (v.status === "recovery_available"
    ? v.recommended !== null && v.trigger !== null
    : v.recommended === null && v.alternatives.length === 0);

const ROUTE_STATUSES = [
  "NORMAL",
  "MINOR_DEVIATION",
  "MAJOR_DEVIATION",
  "NO_ACTIVE_TRIP",
  "NO_ROUTE",
  "NO_LIVE_DATA",
  "STALE",
  "INVALID_LOCATION",
];

export const isRouteStatus: Guard<RouteStatusResponse> = (v): v is RouteStatusResponse =>
  isObj(v) &&
  isStr(v.bus_id) &&
  ROUTE_STATUSES.includes(String(v.route_status)) &&
  (v.deviation_distance_m === null || isNum(v.deviation_distance_m)) &&
  (v.expected_route === null || isLineString(v.expected_route)) &&
  (v.current_location === null ||
    (isObj(v.current_location) &&
      isNum(v.current_location.lat) &&
      isNum(v.current_location.lon))) &&
  isStr(v.evaluated_at);

const ALERT_TYPES = [
  "BUS_APPROACHING",
  "BUS_DELAYED",
  "CAPACITY_WARNING",
  "ROUTE_DEVIATION",
  "MISSED_BUS",
  "ALTERNATIVE_BUS_AVAILABLE",
  "BREAKDOWN",
  "BROADCAST",
];

export const isAlert: Guard<Alert> = (v): v is Alert =>
  isObj(v) &&
  isStr(v.alert_id) &&
  ALERT_TYPES.includes(String(v.type)) &&
  isStr(v.title) &&
  isStr(v.message) &&
  ["info", "warning", "critical"].includes(String(v.severity)) &&
  isStr(v.timestamp) &&
  isBool(v.read) &&
  isBool(v.active) &&
  (v.recipient === "student" || v.recipient === "admin");

// ---- Feature 16 — student commute experience

const PHASES = [
  "unassigned",
  "no_trip",
  "waiting",
  "approaching",
  "at_stop",
  "on_board",
  "completed",
  "missed",
  "recovery_available",
];

export const isStudentCommute: Guard<StudentCommuteOut> = (v): v is StudentCommuteOut =>
  isObj(v) &&
  isStr(v.student_id) &&
  PHASES.includes(String(v.phase)) &&
  isStr(v.phase_reason) &&
  isCommuteDecision(v.decision) &&
  isRecovery(v.recovery) &&
  isMyBoarding(v.boarding) &&
  Array.isArray(v.alerts) &&
  v.alerts.every(isAlert) &&
  (v.bus === null || isBus(v.bus));

const isHistoryEntry = (v: unknown): v is CommuteHistoryEntry =>
  isObj(v) &&
  isStr(v.trip_id) &&
  isStr(v.bus_id) &&
  isStr(v.outcome) &&
  isStr(v.trip_status) &&
  isBool(v.boarded) &&
  isStr(v.scheduled_departure);

export const isCommuteHistory: Guard<CommuteHistoryOut> = (v): v is CommuteHistoryOut =>
  isObj(v) && isStr(v.student_id) && Array.isArray(v.entries) && v.entries.every(isHistoryEntry);
