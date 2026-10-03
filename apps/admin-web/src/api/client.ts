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
