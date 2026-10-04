/**
 * Typed client for the CampusRide backend — Driver App (Feature 12).
 *
 * Every value the app shows comes from these endpoints. The app never sends a bus,
 * route or trip id: the backend derives them from the signed-in driver.
 */
import type { components } from "./schema.gen";

type Schemas = components["schemas"];
export type TokenOut = Schemas["TokenOut"];
export type MeOut = Schemas["MeOut"];
export type DriverDashboard = Schemas["DriverDashboardOut"];
export type DriverRouteView = Schemas["DriverRouteViewOut"];
export type Occupancy = Schemas["OccupancyOut"];
export type TripBoarding = Schemas["TripBoardingOut"];
export type TripState = DriverDashboard["trip_state"];
export type GpsState = DriverDashboard["gps"];

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

const TRIP_STATES = ["READY", "ACTIVE", "COMPLETED", "NO_TRIP", "NO_ASSIGNMENT"];
const GPS_STATES = ["LIVE", "STALE", "UNAVAILABLE"];

const isToken: Guard<TokenOut> = (v): v is TokenOut => isObj(v) && isStr(v.access_token);
const isMe: Guard<MeOut> = (v): v is MeOut => isObj(v) && isStr(v.id) && isStr(v.role);
export const isDashboard: Guard<DriverDashboard> = (v): v is DriverDashboard =>
  isObj(v) &&
  isObj(v.driver) &&
  isStr(v.driver.name) &&
  TRIP_STATES.includes(String(v.trip_state)) &&
  GPS_STATES.includes(String(v.gps)) &&
  typeof v.can_start === "boolean" &&
  typeof v.can_stop === "boolean" &&
  (v.live === null ||
    (isObj(v.live) &&
      isInt(v.live.speed_kmh) &&
      isInt(v.live.occupancy) &&
      isInt(v.live.capacity)));
const isRouteView: Guard<DriverRouteView> = (v): v is DriverRouteView =>
  isObj(v) && Array.isArray(v.stops);
const isOccupancy: Guard<Occupancy> = (v): v is Occupancy =>
  isObj(v) && isInt(v.occupancy) && isInt(v.capacity) && isInt(v.available_seats);
const isTripBoarding: Guard<TripBoarding> = (v): v is TripBoarding =>
  isObj(v) && isInt(v.total_boarded);

export interface DriverApiOptions {
  baseUrl: string;
  getToken?: () => string | null;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

export class DriverApi {
  private readonly baseUrl: string;
  private readonly getToken: () => string | null;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(opts: DriverApiOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, "");
    this.getToken = opts.getToken ?? (() => null);
    this.fetchImpl = opts.fetchImpl ?? ((...args) => globalThis.fetch(...args));
    this.timeoutMs = opts.timeoutMs ?? 10_000;
  }

  /** Feature 14: the WebSocket endpoint next to this REST base URL, and the current token. */
  realtimeUrl(): string {
    return `${this.baseUrl.replace(/^http/, "ws")}/ws`;
  }

  token(): string | null {
    return this.getToken();
  }

  mockLogin(email: string): Promise<TokenOut> {
    return this.request("/auth/mock-login", isToken, {
      method: "POST",
      body: { email },
      auth: false,
    });
  }

  me(token?: string): Promise<MeOut> {
    return this.request("/me", isMe, { token });
  }

  /** Profile, assigned bus/route, current or next trip and the live bus state. */
  dashboard(): Promise<DriverDashboard> {
    return this.request("/driver/me", isDashboard);
  }

  startTrip(): Promise<DriverDashboard> {
    return this.request("/driver/trip/start", isDashboard, { method: "POST" });
  }

  stopTrip(): Promise<DriverDashboard> {
    return this.request("/driver/trip/stop", isDashboard, { method: "POST" });
  }

  /** One synthetic GPS fix from the BACKEND simulator (no coordinates are made here). */
  simulateGps(): Promise<DriverDashboard> {
    return this.request("/driver/simulate-gps", isDashboard, { method: "POST" });
  }

  route(): Promise<DriverRouteView> {
    return this.request("/driver/route", isRouteView);
  }

  occupancy(busId: string): Promise<Occupancy> {
    return this.request(`/buses/${encodeURIComponent(busId)}/occupancy`, isOccupancy);
  }

  tripBoarding(tripId: string): Promise<TripBoarding> {
    return this.request(`/trips/${encodeURIComponent(tripId)}/boarding`, isTripBoarding);
  }

  private async request<T>(
    path: string,
    guard: Guard<T>,
    opts: { method?: "GET" | "POST"; body?: unknown; auth?: boolean; token?: string } = {},
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    const token = opts.auth === false ? null : (opts.token ?? this.getToken());
    if (token) headers.Authorization = `Bearer ${token}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method: opts.method ?? "GET",
        headers,
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
        signal: controller.signal,
      });
    } catch {
      throw new ApiError(0, "backend_unavailable", "Connection unavailable");
    } finally {
      clearTimeout(timer);
    }
    const data: unknown = await res.json().catch(() => null);
    if (!res.ok) {
      const err = isObj(data) && isObj(data.error) ? data.error : {};
      throw new ApiError(
        res.status,
        isStr(err.code) ? err.code : "http_error",
        isStr(err.message) ? err.message : `HTTP ${res.status}`,
      );
    }
    if (!guard(data)) {
      throw new ApiError(200, "malformed_response", "Unexpected response from the backend.");
    }
    return data;
  }
}
