/**
 * Minimal typed client for the CampusRide backend (admin dashboard).
 *
 * Same contract as the student app's client: generated OpenAPI types + runtime
 * guards, errors as `ApiError {status, code}`. Only the endpoints the admin
 * dashboard needs. (The two apps don't share a package yet — see README.)
 */
import type { components } from "./schema.gen";

type Schemas = components["schemas"];
export type TokenOut = Schemas["TokenOut"];
export type MeOut = Schemas["MeOut"];
export type BusOut = Schemas["BusOut"];
export type BusLiveOut = Schemas["BusLiveOut"];
export type TripBoardingOut = Schemas["TripBoardingOut"];
export type BoardingEventOut = Schemas["BoardingEventOut"];
export type RouteStatus = Schemas["RouteStatus"];
export type RouteStatusResponse = Schemas["RouteStatusOut"];
export type RouteDeviationDemoMode = Schemas["RouteDeviationIn"]["mode"];
export type AlertOut = Schemas["AlertOut"];
export type SimStatusOut = Schemas["SimStatusOut"];
// Feature 13 — transport admin dashboard (/admin/*)
export type AdminOverview = Schemas["AdminOverviewOut"];
export type AdminFleet = Schemas["AdminFleetOut"];
export type FleetBus = Schemas["AdminFleetBusOut"];
export type OperationalStatus = FleetBus["operational_status"];
export type AdminRoute = Schemas["AdminRouteOut"];
export type AdminSchedule = Schemas["AdminScheduleOut"];
export type ScheduleTrip = Schemas["ScheduleTripOut"];
export type AdminAnalytics = Schemas["AdminAnalyticsOut"];
export type LabelValue = Schemas["LabelValueOut"];
export type RouteDetail = Schemas["RouteDetailOut"];

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

type Guard<T> = (v: unknown) => v is T;
type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isInt = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v);
const isIntOrNull = (v: unknown) => v === null || isInt(v);
const arrayOf =
  <T>(g: Guard<T>): Guard<T[]> =>
  (v): v is T[] =>
    Array.isArray(v) && v.every(g);

const isToken: Guard<TokenOut> = (v): v is TokenOut => isObj(v) && isStr(v.access_token);
const isMe: Guard<MeOut> = (v): v is MeOut => isObj(v) && isStr(v.id) && isStr(v.role);
const isLive = (v: unknown): v is BusLiveOut =>
  isObj(v) &&
  isInt(v.occupancy) &&
  isIntOrNull(v.available_seats) &&
  isIntOrNull(v.occupancy_percentage) &&
  isInt(v.boarded_count) &&
  isStr(v.last_updated);
const isBus: Guard<BusOut> = (v): v is BusOut =>
  isObj(v) && isStr(v.id) && isInt(v.capacity) && (v.live === null || isLive(v.live));
const isEvent: Guard<BoardingEventOut> = (v): v is BoardingEventOut =>
  isObj(v) && isStr(v.boarding_id) && isStr(v.stop_id) && isStr(v.timestamp);
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
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isLatLon = (v: unknown) => isObj(v) && isNum(v.lat) && isNum(v.lon);
const isRouteStatus: Guard<RouteStatusResponse> = (v): v is RouteStatusResponse =>
  isObj(v) &&
  isStr(v.bus_id) &&
  ROUTE_STATUSES.includes(String(v.route_status)) &&
  (v.deviation_distance_m === null || isNum(v.deviation_distance_m)) &&
  (v.expected_route === null ||
    (isObj(v.expected_route) && Array.isArray(v.expected_route.coordinates))) &&
  (v.current_location === null || isLatLon(v.current_location)) &&
  (v.nearest_route_point === null || isLatLon(v.nearest_route_point));
const isAlert: Guard<AlertOut> = (v): v is AlertOut =>
  isObj(v) &&
  isStr(v.alert_id) &&
  isStr(v.type) &&
  isStr(v.title) &&
  isStr(v.message) &&
  isStr(v.timestamp) &&
  typeof v.read === "boolean" &&
  typeof v.active === "boolean" &&
  (v.recipient === "admin" || v.recipient === "student");
const isSimStatus: Guard<SimStatusOut> = (v): v is SimStatusOut =>
  isObj(v) && typeof v.enabled === "boolean" && isObj(v.route_deviation);
const isArr = Array.isArray;
const isOverview: Guard<AdminOverview> = (v): v is AdminOverview =>
  isObj(v) &&
  isInt(v.total_buses) &&
  isInt(v.active_trips) &&
  isInt(v.students) &&
  isInt(v.passengers_today) &&
  isObj(v.trips_today) &&
  isObj(v.alerts);
const isFleetBus: Guard<FleetBus> = (v): v is FleetBus =>
  isObj(v) &&
  isStr(v.bus_id) &&
  isStr(v.route_id) &&
  isStr(v.operational_status) &&
  isInt(v.capacity) &&
  (v.occupancy === null || isInt(v.occupancy)) &&
  (v.location === null || isLatLon(v.location)) &&
  isArr(v.active_alerts);
const isFleet: Guard<AdminFleet> = (v): v is AdminFleet =>
  isObj(v) && arrayOf(isFleetBus)(v.buses) && isObj(v.options) && isStr(v.sim_time);
const isAdminRoute: Guard<AdminRoute> = (v): v is AdminRoute =>
  isObj(v) && isStr(v.id) && isArr(v.directions) && isArr(v.active_buses) && isObj(v.trips_today);
const isScheduleTrip = (v: unknown): v is ScheduleTrip =>
  isObj(v) &&
  isStr(v.trip_id) &&
  isStr(v.bus_id) &&
  isStr(v.scheduled_departure) &&
  isStr(v.status);
const isSchedule: Guard<AdminSchedule> = (v): v is AdminSchedule =>
  isObj(v) && isStr(v.service_date) && arrayOf(isScheduleTrip)(v.trips);
const isAnalytics: Guard<AdminAnalytics> = (v): v is AdminAnalytics =>
  isObj(v) &&
  isObj(v.live) &&
  isObj(v.synthetic) &&
  v.synthetic.synthetic === true &&
  isArr(v.live.passengers_per_route);
const isRouteDetail: Guard<RouteDetail> = (v): v is RouteDetail =>
  isObj(v) && isStr(v.id) && isObj(v.path) && isArr(v.path.coordinates) && isArr(v.directions);
const isTripBoarding: Guard<TripBoardingOut> = (v): v is TripBoardingOut =>
  isObj(v) && isStr(v.trip_id) && isInt(v.total_boarded) && arrayOf(isEvent)(v.events);

export interface AdminApiOptions {
  baseUrl: string;
  getToken?: () => string | null;
  onUnauthorized?: () => void;
  fetchImpl?: typeof fetch;
}

export class AdminApi {
  private readonly baseUrl: string;
  private readonly getToken: () => string | null;
  private readonly onUnauthorized?: () => void;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: AdminApiOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, "");
    this.getToken = opts.getToken ?? (() => null);
    this.onUnauthorized = opts.onUnauthorized;
    this.fetchImpl = opts.fetchImpl ?? ((...args) => globalThis.fetch(...args));
  }

  /** Feature 14: the WebSocket endpoint next to this REST base URL, and the current token. */
  realtimeUrl(): string {
    return `${this.baseUrl.replace(/^http/, "ws")}/ws`;
  }

  token(): string | null {
    return this.getToken();
  }

  mockLogin(email: string): Promise<TokenOut> {
    return this.request(
      "/auth/mock-login",
      { method: "POST", body: { email }, auth: false },
      isToken,
    );
  }

  me(): Promise<MeOut> {
    return this.request("/me", {}, isMe);
  }

  /** Fleet + live state (occupancy, seats, % and QR boardings computed by the backend). */
  listBuses(): Promise<BusOut[]> {
    return this.request("/buses", {}, arrayOf(isBus));
  }

  /** Boarding events of a trip (admins see every event). */
  tripBoarding(tripId: string): Promise<TripBoardingOut> {
    return this.request(`/trips/${encodeURIComponent(tripId)}/boarding`, {}, isTripBoarding);
  }

  /** Backend route deviation of one bus vs. its PLANNED route (Feature 10). */
  routeStatus(busId: string): Promise<RouteStatusResponse> {
    return this.request(`/buses/${encodeURIComponent(busId)}/route-status`, {}, isRouteStatus);
  }

  /** Demo control: shift a simulated bus's GPS off its route (the route itself never changes). */
  setRouteDeviation(mode: RouteDeviationDemoMode, busId: string | null): Promise<SimStatusOut> {
    return this.request(
      "/sim/route-deviation",
      { method: "POST", body: { mode, bus_id: busId } },
      isSimStatus,
    );
  }

  /** Fleet/operational alerts (Feature 11; the backend never returns students' personal ones).
   * `true` → active only, `false` → resolved only, `null` → both. */
  alerts(active: boolean | null = true): Promise<AlertOut[]> {
    const q = active === null ? "" : `?active=${active}`;
    return this.request(`/alerts${q}`, {}, arrayOf(isAlert));
  }

  markAlertRead(alertId: string): Promise<AlertOut> {
    return this.request(
      `/alerts/${encodeURIComponent(alertId)}/read`,
      { method: "PATCH" },
      isAlert,
    );
  }

  // ---------------------------------------------------------- Feature 13 (admin only)

  /** KPIs: buses, trips, students, passengers today, delays, deviations, alert counts. */
  adminOverview(): Promise<AdminOverview> {
    return this.request("/admin/overview", {}, isOverview);
  }

  /** Every bus as the backend sees it (ETA, occupancy, delay, route status, alerts). */
  adminFleet(): Promise<AdminFleet> {
    return this.request("/admin/fleet", {}, isFleet);
  }

  /** Routes with today's operational aggregates (read-only). */
  adminRoutes(): Promise<AdminRoute[]> {
    return this.request("/admin/routes", {}, arrayOf(isAdminRoute));
  }

  /** Today's trips with assigned bus and driver (read-only). */
  adminSchedule(): Promise<AdminSchedule> {
    return this.request("/admin/schedule", {}, isSchedule);
  }

  /** Live aggregates + a separate block of labelled synthetic demo history. */
  adminAnalytics(): Promise<AdminAnalytics> {
    return this.request("/admin/analytics", {}, isAnalytics);
  }

  /** Route geometry and ordered stops of both directions (reference data). */
  routeDetail(routeId: string): Promise<RouteDetail> {
    return this.request(`/routes/${encodeURIComponent(routeId)}`, {}, isRouteDetail);
  }

  private async request<T>(
    path: string,
    opts: { method?: "GET" | "POST" | "PATCH"; body?: unknown; auth?: boolean },
    guard: Guard<T>,
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    const token = opts.auth === false ? null : this.getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method: opts.method ?? "GET",
        headers,
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      });
    } catch {
      throw new ApiError(0, "backend_unavailable", "The CampusRide backend is not reachable.");
    }
    const data: unknown = await res.json().catch(() => null);
    if (!res.ok) {
      const err = isObj(data) && isObj(data.error) ? data.error : {};
      if (res.status === 401) this.onUnauthorized?.();
      throw new ApiError(
        res.status,
        isStr(err.code) ? err.code : "http_error",
        isStr(err.message) ? err.message : `HTTP ${res.status}`,
      );
    }
    if (!guard(data)) {
      throw new ApiError(
        200,
        "malformed_response",
        `Unexpected response from the backend for ${path}.`,
      );
    }
    return data;
  }
}
