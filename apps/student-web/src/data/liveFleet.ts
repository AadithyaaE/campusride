/**
 * Live fleet state from the BACKEND (synthetic simulator → telemetry → tracking)
 * and the backend's stop matching for the signed-in student.
 *
 * Feature 14 — real time:
 * 1. REST loads everything once: `GET /buses`, `/students/me/arrivals` (matching + ETA),
 *    `/students/me/bus-options`, `/students/me/commute` (Feature 16: decision, recovery,
 *    boarding, own active alerts and the backend's commute phase in ONE call), `/alerts`
 *    (own notifications) and `/sim/status`.
 * 2. The WebSocket (`/api/v1/ws`) then pushes changes:
 *    - `bus.state.updated` → the bus's `GET /buses` item, applied in place;
 *    - `alert.*`           → the student's OWN alerts (the backend never sends others');
 *    - `eta.updated`, `occupancy.updated`, `route.deviation`, `trip.*` for a bus relevant
 *      to this student, and the student's own `boarding.updated` → the student-specific
 *      backend answers (arrivals, comparison, today's commute) are re-fetched, at most once
 *      per 1.5 s;
 *    - `sim.reset` → everything is re-fetched.
 * 3. After every (re)connection REST is fetched once (no missed events). While the socket
 *    is down, REST is polled every 10 s; while it is live, only every 60 s as a safety net.
 *
 * The browser never computes bus positions, ETAs, occupancy or decisions.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { useApi } from "../api/ApiContext";
import type {
  Alert,
  BusOptionsOut,
  BusOut,
  CommuteDecisionOut,
  MyArrivalsOut,
  RecoveryOut,
  SimStatusOut,
  StudentCommuteOut,
} from "../api/types";
import { RealtimeClient, type RealtimeStatus, type WsEnvelope } from "../realtime/client";

/** Legacy fast poll interval (kept for reference in the UI copy). */
export const POLL_MS = 3_000;
/** WebSocket down → REST polling of live data at this slower interval. */
export const FALLBACK_POLL_MS = 10_000;
/** WebSocket live → occasional safety re-sync over REST. */
export const RESYNC_MS = 60_000;
/** Student-specific answers are re-fetched at most this often after relevant pushes. */
export const DERIVED_THROTTLE_MS = 1_500;

export interface LiveFleet {
  buses: BusOut[] | null;
  /** Backend matching + ETAs for the student's boarding stop (assigned bus + others). */
  arrivals: MyArrivalsOut | null;
  /** Backend comparison of the buses serving the boarding stop (indicators, crowding). */
  options: BusOptionsOut | null;
  /** Feature 16: today's commute (phase, trip, boarding…) — the backend's single answer. */
  today: StudentCommuteOut | null;
  /** Backend "Will I make my bus?" decision for the ASSIGNED bus (from `today`). */
  commute: CommuteDecisionOut | null;
  /** Backend missed-bus recovery (suggestions only, from `today`). */
  recovery: RecoveryOut | null;
  /** The student's own backend alerts, newest first (Feature 11). */
  alerts: Alert[] | null;
  /** Mark an alert read (optimistic; the backend stays authoritative). */
  markAlertRead: (alertId: string) => Promise<void>;
  sim: SimStatusOut | null;
  error: Error | null;
  /** Wall-clock time of the last successful fetch of the ETA-bearing data. */
  fetchedAt: Date | null;
  /** Feature 14 connection state of the live feed. */
  realtime: RealtimeStatus;
  refresh: () => Promise<void>;
  control: {
    start: () => Promise<void>;
    pause: () => Promise<void>;
    reset: () => Promise<void>;
    setSpeed: (speed: number) => Promise<void>;
  };
}

const RELEVANT_TYPES = new Set(["eta.updated", "occupancy.updated", "route.deviation"]);

/** Newer-or-equal backend fix wins (events may arrive late or twice). */
function isNewer(next: BusOut, cur: BusOut): boolean {
  return (next.live?.last_updated ?? "") >= (cur.live?.last_updated ?? "");
}

export function useLiveFleet(): LiveFleet {
  const api = useApi();
  const [buses, setBuses] = useState<BusOut[] | null>(null);
  const [arrivals, setArrivals] = useState<MyArrivalsOut | null>(null);
  const [options, setOptions] = useState<BusOptionsOut | null>(null);
  const [today, setToday] = useState<StudentCommuteOut | null>(null);
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [sim, setSim] = useState<SimStatusOut | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);
  const [realtime, setRealtime] = useState<RealtimeStatus>("connecting");

  const refresh = useCallback(async () => {
    try {
      const [b, a, o, t, n, s] = await Promise.all([
        api.listBuses(),
        api.myArrivals(),
        api.myBusOptions(),
        api.myCommute(),
        api.alerts({ limit: 20 }),
        api.simStatus(),
      ]);
      setBuses(b);
      setArrivals(a);
      setOptions(o);
      setToday(t);
      setAlerts(n);
      setSim(s);
      setError(null);
      setFetchedAt(new Date());
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    }
  }, [api]);

  /** Only the student-specific backend answers (they depend on the buses that moved). */
  const refreshDerived = useCallback(async () => {
    try {
      const [a, o, t] = await Promise.all([api.myArrivals(), api.myBusOptions(), api.myCommute()]);
      setArrivals(a);
      setOptions(o);
      setToday(t);
      setFetchedAt(new Date());
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    }
  }, [api]);

  // Buses whose changes affect this student's answers (assigned bus + buses at the stop).
  const relevant = useRef<Set<string>>(new Set());
  useEffect(() => {
    const ids = new Set<string>();
    if (arrivals?.status === "assigned") {
      if (arrivals.assigned_bus_id) ids.add(arrivals.assigned_bus_id);
      arrivals.arrivals.forEach((x) => ids.add(x.bus_id));
    }
    options?.options.forEach((x) => ids.add(x.bus_id));
    relevant.current = ids;
  }, [arrivals, options]);

  const derivedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleDerived = useCallback(() => {
    if (derivedTimer.current) return; // throttle: one re-fetch per window
    derivedTimer.current = setTimeout(() => {
      derivedTimer.current = null;
      void refreshDerived();
    }, DERIVED_THROTTLE_MS);
  }, [refreshDerived]);

  const onEvent = useCallback(
    (e: WsEnvelope) => {
      const busId = (e.data as { bus_id?: string }).bus_id;
      const isRelevant = (id: string | undefined) =>
        !id || relevant.current.size === 0 || relevant.current.has(id);
      switch (e.type) {
        case "bus.state.updated": {
          const bus = (e.data as { bus: BusOut }).bus;
          setBuses((prev) =>
            prev ? prev.map((b) => (b.id === bus.id && isNewer(bus, b) ? bus : b)) : prev,
          );
          return;
        }
        case "alert.created":
        case "alert.updated":
        case "alert.resolved": {
          const a = e.data as unknown as Alert;
          if (a.recipient !== "student") return;
          setAlerts((prev) => {
            const rest = (prev ?? []).filter((x) => x.alert_id !== a.alert_id);
            return [a, ...rest].sort((x, y) => y.timestamp.localeCompare(x.timestamp));
          });
          return;
        }
        case "alert.read": {
          const id = (e.data as { alert_id: string }).alert_id;
          setAlerts(
            (prev) => prev && prev.map((x) => (x.alert_id === id ? { ...x, read: true } : x)),
          );
          return;
        }
        case "trip.started":
        case "trip.completed":
          scheduleDerived(); // a bus may have started (or stopped) serving the stop
          return;
        case "boarding.updated":
          scheduleDerived(); // the backend only sends the student their OWN boarding
          return;
        case "sim.reset":
          void refresh();
          return;
        default:
          if (RELEVANT_TYPES.has(e.type) && isRelevant(busId)) scheduleDerived();
      }
    },
    [refresh, scheduleDerived],
  );

  const latest = useRef({ onEvent, refresh });
  useEffect(() => {
    latest.current = { onEvent, refresh };
  });

  // Initial REST state, then the socket; REST re-sync after every (re)connection.
  useEffect(() => {
    const first = setTimeout(() => void latest.current.refresh(), 0);
    const client = new RealtimeClient({
      url: api.realtimeUrl(),
      getToken: () => api.token(),
      onEvent: (e) => latest.current.onEvent(e),
      onOpen: () => void latest.current.refresh(),
      onStatus: setRealtime,
      onUnauthorized: () => api.unauthorized(), // refused session → sign out (same as REST 401)
    });
    client.start();
    return () => {
      clearTimeout(first);
      client.stop();
      if (derivedTimer.current) clearTimeout(derivedTimer.current);
      derivedTimer.current = null;
    };
  }, [api]);

  // Fallback polling while the socket is down; a slow safety re-sync while it is live.
  const interval = realtime === "live" ? RESYNC_MS : FALLBACK_POLL_MS;
  useEffect(() => {
    const id = setInterval(() => void latest.current.refresh(), interval);
    return () => clearInterval(id);
  }, [interval]);

  const act = useCallback(
    (call: () => Promise<SimStatusOut>) => async () => {
      try {
        setSim(await call());
      } catch (e) {
        setError(e instanceof Error ? e : new Error(String(e)));
      }
      await refresh();
    },
    [refresh],
  );

  return {
    buses,
    arrivals,
    options,
    today,
    commute: today?.decision ?? null,
    recovery: today?.recovery ?? null,
    alerts,
    markAlertRead: async (alertId: string) => {
      setAlerts(
        (prev) => prev && prev.map((x) => (x.alert_id === alertId ? { ...x, read: true } : x)),
      );
      try {
        const updated = await api.markAlertRead(alertId);
        setAlerts((prev) => prev && prev.map((x) => (x.alert_id === alertId ? updated : x)));
      } catch (e) {
        setError(e instanceof Error ? e : new Error(String(e)));
        await refresh(); // re-sync with the backend
      }
    },
    sim,
    error,
    fetchedAt,
    realtime,
    refresh,
    control: {
      start: act(() => api.simStart()),
      pause: act(() => api.simPause()),
      reset: act(() => api.simReset()),
      setSpeed: (speed: number) => act(() => api.simSetSpeed(speed))(),
    },
  };
}
