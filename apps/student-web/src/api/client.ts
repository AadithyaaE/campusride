/**
 * Typed client for the CampusRide FastAPI backend.
 *
 * Every network call in the app goes through this class. It
 *  - prefixes VITE_API_BASE_URL and attaches the bearer token,
 *  - maps both backend error envelopes to `ApiError`
 *      { "error": { "code", "message" } }   (domain errors)
 *      { "detail": [ ... ] }                 (FastAPI 422 validation)
 *  - turns network failures/timeouts into `BackendUnavailableError`,
 *  - validates response shapes at runtime (`MalformedResponseError`).
 *
 * Only endpoints that exist in Phase 1 are exposed here.
 */
import {
  arrayOf,
  isHealth,
  isBus,
  isBusEta,
  isBusOptions,
  isCommuteDecision,
  isBusDetail,
  isMe,
  isMyArrivals,
  isMyAssignment,
  isMyStopBuses,
  isNearbyStop,
  isRouteDetail,
  isRouteSummary,
  isSimStatus,
  isStopArrivals,
  isStopBuses,
  isStop,
  isStopService,
  isToken,
  type Guard,
} from "./guards";
import type {
  BusEtaOut,
  BusOptionsOut,
  CommuteDecisionOut,
  MyArrivalsOut,
  StopArrivalsOut,
  BusDetailOut,
  BusOut,
  HealthOut,
  MeOut,
  MyAssignmentOut,
  MyStopBusesOut,
  NearbyStopOut,
  RouteDetailOut,
  RouteSummaryOut,
  SimStatusOut,
  StopBusesOut,
  StopOut,
  StopServiceOut,
  TokenOut,
} from "./types";

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

/** The backend could not be reached (not running, network down, CORS, timeout). */
export class BackendUnavailableError extends ApiError {
  constructor(message = "The CampusRide backend is not reachable.") {
    super(0, "backend_unavailable", message);
    this.name = "BackendUnavailableError";
  }
}

/** Missing, invalid or expired bearer token. */
export class UnauthorizedError extends ApiError {
  constructor(message: string) {
    super(401, "unauthorized", message);
    this.name = "UnauthorizedError";
  }
}

/** The backend answered, but not with the shape this app was built against. */
export class MalformedResponseError extends ApiError {
  constructor(path: string) {
    super(200, "malformed_response", `Unexpected response from the backend for ${path}.`);
    this.name = "MalformedResponseError";
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  getToken?: () => string | null;
  /** Called on any 401 so the session can be cleared. */
  onUnauthorized?: () => void;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

interface RequestOptions<T> {
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
  auth?: boolean;
  query?: Record<string, string | number>;
  guard: Guard<T>;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly getToken: () => string | null;
  private readonly onUnauthorized?: () => void;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(opts: ApiClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, "");
    this.getToken = opts.getToken ?? (() => null);
    this.onUnauthorized = opts.onUnauthorized;
    this.fetchImpl = opts.fetchImpl ?? ((...args) => globalThis.fetch(...args));
    this.timeoutMs = opts.timeoutMs ?? 10_000;
  }

  // ------------------------------------------------------------------ endpoints

  health(): Promise<HealthOut> {
    return this.request("/health", { auth: false, guard: isHealth });
  }

  mockLogin(email: string): Promise<TokenOut> {
    return this.request("/auth/mock-login", {
      method: "POST",
      body: { email },
      auth: false,
      guard: isToken,
    });
  }

  me(): Promise<MeOut> {
    return this.request("/me", { guard: isMe });
  }

  /** The signed-in student's college-assigned bus (read-only; students cannot change it). */
  myAssignment(): Promise<MyAssignmentOut> {
    return this.request("/students/me/assignment", { guard: isMyAssignment });
  }

  /** The fleet with each bus's current live state (synthetic for simulated buses). */
  listBuses(): Promise<BusOut[]> {
    return this.request("/buses", { guard: arrayOf(isBus) });
  }

  getBus(busId: string): Promise<BusDetailOut> {
    return this.request(`/buses/${encodeURIComponent(busId)}`, { guard: isBusDetail });
  }

  // ---- development / demo simulator controls (backend decides who may use them)

  simStatus(): Promise<SimStatusOut> {
    return this.request("/sim/status", { guard: isSimStatus });
  }

  simStart(): Promise<SimStatusOut> {
    return this.request("/sim/start", { method: "POST", guard: isSimStatus });
  }

  simPause(): Promise<SimStatusOut> {
    return this.request("/sim/pause", { method: "POST", guard: isSimStatus });
  }

  simReset(): Promise<SimStatusOut> {
    return this.request("/sim/reset", { method: "POST", guard: isSimStatus });
  }

  simSetSpeed(speed: number): Promise<SimStatusOut> {
    return this.request("/sim/speed", { method: "PUT", body: { speed }, guard: isSimStatus });
  }

  /** Backend stop matching: the assigned bus + other buses serving the student's boarding stop. */
  myStopBuses(): Promise<MyStopBusesOut> {
    return this.request("/students/me/stop/buses", { guard: isMyStopBuses });
  }

  /** Backend stop matching: buses whose current route direction serves ``stopId``. */
  stopBuses(stopId: string, direction?: "to_campus" | "from_campus"): Promise<StopBusesOut> {
    return this.request(`/stops/${encodeURIComponent(stopId)}/buses`, {
      query: direction ? { direction } : undefined,
      guard: isStopBuses,
    });
  }

  /** Backend ETAs for every bus serving the student's ASSIGNED boarding stop (incl. their bus). */
  myArrivals(): Promise<MyArrivalsOut> {
    return this.request("/students/me/arrivals", { guard: isMyArrivals });
  }

  /** Backend ETAs for buses serving ``stopId``, ordered by ETA. */
  stopArrivals(stopId: string, direction?: "to_campus" | "from_campus"): Promise<StopArrivalsOut> {
    return this.request(`/stops/${encodeURIComponent(stopId)}/arrivals`, {
      query: direction ? { direction } : undefined,
      guard: isStopArrivals,
    });
  }

  /** Backend ETA of one bus at one stop (409 when its current direction doesn't serve the stop). */
  busEta(busId: string, stopId: string): Promise<BusEtaOut> {
    return this.request(`/buses/${encodeURIComponent(busId)}/eta`, {
      query: { stop_id: stopId },
      guard: isBusEta,
    });
  }

  /**
   * Backend multi-bus comparison for the student's ASSIGNED boarding stop (Feature 6):
   * ETA, crowding and indicators per bus. Read-only — never changes the assignment.
   */
  myBusOptions(): Promise<BusOptionsOut> {
    return this.request("/students/me/bus-options", { guard: isBusOptions });
  }

  /**
   * Backend "Will I make my bus?" for the ASSIGNED bus and boarding stop (Feature 7).
   * Derived entirely from the assignment — no bus or stop can be passed in.
   */
  myCommuteDecision(): Promise<CommuteDecisionOut> {
    return this.request("/students/me/commute-decision", { guard: isCommuteDecision });
  }

  listStops(): Promise<StopOut[]> {
    return this.request("/stops", { guard: arrayOf(isStop) });
  }

  nearbyStops(params: {
    lat: number;
    lng: number;
    radiusM?: number;
    limit?: number;
  }): Promise<NearbyStopOut[]> {
    const query: Record<string, number> = { lat: params.lat, lng: params.lng };
    if (params.radiusM !== undefined) query.radius_m = params.radiusM;
    if (params.limit !== undefined) query.limit = params.limit;
    return this.request("/stops/nearby", { query, guard: arrayOf(isNearbyStop) });
  }

  getStop(stopId: string): Promise<StopOut> {
    return this.request(`/stops/${encodeURIComponent(stopId)}`, { guard: isStop });
  }

  stopRoutes(stopId: string): Promise<StopServiceOut[]> {
    return this.request(`/stops/${encodeURIComponent(stopId)}/routes`, {
      guard: arrayOf(isStopService),
    });
  }

  listRoutes(): Promise<RouteSummaryOut[]> {
    return this.request("/routes", { guard: arrayOf(isRouteSummary) });
  }

  getRoute(routeId: string): Promise<RouteDetailOut> {
    return this.request(`/routes/${encodeURIComponent(routeId)}`, { guard: isRouteDetail });
  }

  // ------------------------------------------------------------------ transport

  private async request<T>(path: string, opts: RequestOptions<T>): Promise<T> {
    const url = new URL(this.baseUrl + path);
    for (const [k, v] of Object.entries(opts.query ?? {})) url.searchParams.set(k, String(v));

    const headers: Record<string, string> = { Accept: "application/json" };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    if (opts.auth !== false) {
      const token = this.getToken();
      if (!token) throw new UnauthorizedError("Not signed in.");
      headers.Authorization = `Bearer ${token}`;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let res: Response;
    try {
      res = await this.fetchImpl(url.toString(), {
        method: opts.method ?? "GET",
        headers,
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
        signal: controller.signal,
      });
    } catch {
      throw new BackendUnavailableError(
        `Cannot reach the CampusRide backend at ${this.baseUrl}. Is FastAPI running?`,
      );
    } finally {
      clearTimeout(timer);
    }

    const payload = await readJson(res);

    if (!res.ok) {
      const err = toApiError(res.status, payload);
      if (err instanceof UnauthorizedError) this.onUnauthorized?.();
      throw err;
    }
    if (!opts.guard(payload)) throw new MalformedResponseError(path);
    return payload;
  }
}

async function readJson(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined; // non-JSON body; guards / error mapping handle it
  }
}

function toApiError(status: number, payload: unknown): ApiError {
  let code = `http_${status}`;
  let message = `Request failed with HTTP ${status}.`;

  if (typeof payload === "object" && payload !== null) {
    const p = payload as { error?: { code?: unknown; message?: unknown }; detail?: unknown };
    if (p.error && typeof p.error.message === "string") {
      message = p.error.message;
      if (typeof p.error.code === "string") code = p.error.code;
    } else if (Array.isArray(p.detail) && p.detail.length > 0) {
      code = "validation_error";
      const first = p.detail[0] as { msg?: unknown; loc?: unknown };
      const field = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "";
      message = `${field ? `${field}: ` : ""}${String(first.msg ?? "invalid request")}`;
    } else if (typeof p.detail === "string") {
      message = p.detail;
    }
  }

  if (status === 401) return new UnauthorizedError(message);
  if (status >= 502 && status <= 504) return new BackendUnavailableError(message);
  return new ApiError(status, code, message);
}
