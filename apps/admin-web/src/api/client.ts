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
  isObj(v) && isStr(v.id) && isStr(v.body) && typeof v.active === "boolean";
const isSimStatus: Guard<SimStatusOut> = (v): v is SimStatusOut =>
  isObj(v) && typeof v.enabled === "boolean" && isObj(v.route_deviation);
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

  alerts(activeOnly = true): Promise<AlertOut[]> {
    return this.request(`/alerts${activeOnly ? "?active=true" : ""}`, {}, arrayOf(isAlert));
  }

  private async request<T>(
    path: string,
    opts: { method?: "GET" | "POST"; body?: unknown; auth?: boolean },
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
