/**
 * Real-time client for `/api/v1/ws` (Feature 14). Same file in every CampusRide app.
 *
 * - Authenticates with the REST bearer token as the FIRST message (no token in the URL).
 * - Answers the server's `ping` with `pong`; a silent socket (no message for
 *   2.5 × heartbeat) is closed and reconnected.
 * - Reconnects with backoff 1 s → 2 s → 4 s → 8 s → 16 s → 30 s (capped); never in a loop.
 *   A refused token (4401) stops retrying and calls `onUnauthorized` (the app signs out).
 * - Drops duplicates (event id) and stale envelopes (seq not newer than the last one).
 * - `onOpen` fires after every successful (re)authentication: callers re-fetch the
 *   authoritative REST state once, because events are never the only source of truth.
 *
 * The socket only DISTRIBUTES backend facts; nothing here computes transport values.
 */

export type RealtimeStatus = "connecting" | "live" | "offline";

export type WsEventType =
  | "hello"
  | "ping"
  | "bus.state.updated"
  | "fleet.bus.updated"
  | "driver.state.updated"
  | "trip.started"
  | "trip.completed"
  | "occupancy.updated"
  | "eta.updated"
  | "route.deviation"
  | "alert.created"
  | "alert.updated"
  | "alert.resolved"
  | "alert.read"
  | "boarding.updated"
  | "admin.overview.updated"
  | "sim.reset";

export interface WsEnvelope<T = Record<string, unknown>> {
  id: string;
  type: WsEventType;
  seq: number;
  ts: string;
  sent_at: string;
  scope: string;
  data: T;
}

export interface RealtimeOptions {
  url: string;
  getToken: () => string | null;
  onEvent: (e: WsEnvelope) => void;
  onStatus?: (s: RealtimeStatus) => void;
  /** After every successful (re)connection; `reconnect` is false the first time. */
  onOpen?: (reconnect: boolean) => void;
  /** The backend refused the session (invalid / expired token, disabled account). */
  onUnauthorized?: () => void;
  backoffMs?: number[];
}

export const BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000];
const CLOSE_UNAUTHORIZED = 4401;
const SEEN_LIMIT = 500;

/** `http://host/api/v1` → `ws://host/api/v1/ws` (https → wss). */
export function wsUrl(apiBaseUrl: string): string {
  return `${apiBaseUrl.replace(/\/+$/, "").replace(/^http/, "ws")}/ws`;
}

export class RealtimeClient {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private everLive = false;
  private stopped = true;
  private retry: ReturnType<typeof setTimeout> | null = null;
  private watchdog: ReturnType<typeof setTimeout> | null = null;
  private silenceMs = 60_000;
  private lastSeq = 0;
  private seen = new Set<string>();
  status: RealtimeStatus = "offline";

  constructor(private readonly opts: RealtimeOptions) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      try {
        ws.close(1000, "client stopped");
      } catch {
        /* already closed */
      }
    }
    this.setStatus("offline");
  }

  private setStatus(s: RealtimeStatus) {
    if (this.status === s) return;
    this.status = s;
    this.opts.onStatus?.(s);
  }

  private clearTimers() {
    if (this.retry) clearTimeout(this.retry);
    if (this.watchdog) clearTimeout(this.watchdog);
    this.retry = this.watchdog = null;
  }

  private connect() {
    const token = this.opts.getToken();
    if (!token) {
      this.setStatus("offline");
      return;
    }
    this.setStatus("connecting");
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.opts.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token }));
    ws.onmessage = (m: MessageEvent) => this.receive(ws, String(m.data));
    ws.onerror = () => undefined; // onclose follows
    ws.onclose = (ev: CloseEvent) => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (this.watchdog) clearTimeout(this.watchdog);
      this.setStatus("offline");
      if (ev.code === CLOSE_UNAUTHORIZED) {
        this.stopped = true; // never retry a refused session
        this.opts.onUnauthorized?.();
        return;
      }
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect() {
    if (this.stopped) return;
    const steps = this.opts.backoffMs ?? BACKOFF_MS;
    const delay = steps[Math.min(this.attempt, steps.length - 1)]!;
    this.attempt += 1;
    this.retry = setTimeout(() => {
      this.retry = null;
      if (!this.stopped) this.connect();
    }, delay);
  }

  private armWatchdog(ws: WebSocket) {
    if (this.watchdog) clearTimeout(this.watchdog);
    this.watchdog = setTimeout(() => ws.close(4000, "no heartbeat"), this.silenceMs);
  }

  private receive(ws: WebSocket, raw: string) {
    let e: WsEnvelope;
    try {
      e = JSON.parse(raw) as WsEnvelope;
    } catch {
      return;
    }
    this.armWatchdog(ws);
    if (e.type === "hello") {
      const hb = Number((e.data as { heartbeat_s?: number }).heartbeat_s) || 20;
      this.silenceMs = hb * 2_500 + 5_000;
      this.lastSeq = e.seq;
      this.attempt = 0;
      const reconnect = this.everLive;
      this.everLive = true;
      this.setStatus("live");
      this.armWatchdog(ws);
      this.opts.onOpen?.(reconnect);
      return;
    }
    if (e.type === "ping") {
      ws.send(JSON.stringify({ type: "pong" }));
      return;
    }
    if (this.seen.has(e.id) || e.seq <= this.lastSeq) return; // duplicate or out of order
    this.seen.add(e.id);
    if (this.seen.size > SEEN_LIMIT) this.seen.delete(this.seen.values().next().value!);
    this.lastSeq = e.seq;
    this.opts.onEvent(e);
  }
}
