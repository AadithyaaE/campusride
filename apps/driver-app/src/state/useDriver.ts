/**
 * Driver dashboard state = the BACKEND's `GET /driver/me`.
 *
 * Feature 14: loaded over REST, then kept current by the WebSocket while the driving screen
 * is open — `driver.state.updated` carries the same `/driver/me` answer for THIS driver's
 * bus (the backend never sends another bus's private state). Trip events / a simulator
 * reset re-fetch it; every (re)connection re-fetches it once. Socket down → REST polling
 * every 10 s; socket live → a 60 s safety re-sync only.
 *
 * Start / Stop / Simulate GPS call the backend and show its answer — nothing is set to
 * ACTIVE (or anything else) locally, and no position, speed or occupancy is invented here.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";

import type { DriverApi, DriverDashboard } from "../api/client";
import { RealtimeClient, type RealtimeStatus, type WsEnvelope } from "../realtime/client";
import { friendlyError } from "../utils/messages";

/** WebSocket down → REST polling at this interval. */
export const FALLBACK_POLL_MS = 10_000;
/** WebSocket live → occasional safety re-sync. */
export const RESYNC_MS = 60_000;

export type Action = "start" | "stop" | "gps";

export interface DriverState {
  data: DriverDashboard | null;
  /** Last poll failed (e.g. "Connection unavailable"); the last backend data is kept. */
  error: string | null;
  /** Message from the last action (start/stop/gps) failure. */
  actionError: string | null;
  busy: Action | null;
  /** Feature 14 live-update connection state. */
  realtime: RealtimeStatus;
  refresh: () => Promise<void>;
  act: (a: Action) => Promise<void>;
}

const FAIL: Record<Action, string> = {
  start: "Trip could not be started. Please try again.",
  stop: "Trip could not be stopped. Please try again.",
  gps: "GPS could not be simulated. Please try again.",
};

export function useDriver(api: DriverApi, { polling }: { polling: boolean }): DriverState {
  const [data, setData] = useState<DriverDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Action | null>(null);
  const [realtime, setRealtime] = useState<RealtimeStatus>("connecting");
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const d = await api.dashboard();
      if (!alive.current) return;
      setData(d);
      setError(null);
    } catch (e) {
      if (alive.current) setError(friendlyError(e, "Connection unavailable"));
    }
  }, [api]);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const onEvent = useCallback(
    (e: WsEnvelope) => {
      if (e.type === "driver.state.updated") {
        setData(e.data as unknown as DriverDashboard); // the backend's /driver/me, as pushed
        setError(null);
      } else if (
        e.type === "trip.started" ||
        e.type === "trip.completed" ||
        e.type === "sim.reset"
      ) {
        void refresh();
      }
    },
    [refresh],
  );
  const latest = useRef(onEvent);
  useEffect(() => {
    latest.current = onEvent;
  });

  // REST first, then the socket (re-sync over REST on every (re)connection).
  useEffect(() => {
    if (!polling) return;
    const first = setTimeout(() => void refresh(), 0);
    const client = new RealtimeClient({
      url: api.realtimeUrl(),
      getToken: () => api.token(),
      onEvent: (e) => latest.current(e),
      onOpen: () => void refresh(),
      onStatus: setRealtime,
      onUnauthorized: () => api.unauthorized(), // refused session → sign out (same as REST 401)
    });
    client.start();
    const sub = AppState.addEventListener("change", (st) => {
      if (st === "active") void refresh();
    });
    return () => {
      clearTimeout(first);
      client.stop();
      sub.remove();
    };
  }, [polling, api, refresh]);

  const interval = realtime === "live" ? RESYNC_MS : FALLBACK_POLL_MS;
  useEffect(() => {
    if (!polling) return;
    const id = setInterval(() => {
      if (AppState.currentState !== "background") void refresh();
    }, interval);
    return () => clearInterval(id);
  }, [polling, interval, refresh]);

  const act = useCallback(
    async (a: Action) => {
      setBusy(a);
      setActionError(null);
      try {
        const d =
          a === "start"
            ? await api.startTrip()
            : a === "stop"
              ? await api.stopTrip()
              : await api.simulateGps();
        if (!alive.current) return;
        setData(d); // the backend's confirmed state — only now does the UI change
        setError(null);
      } catch (e) {
        if (!alive.current) return;
        setActionError(friendlyError(e, FAIL[a]));
        await refresh(); // show the ACTUAL backend state after a failure
      } finally {
        if (alive.current) setBusy(null);
      }
    },
    [api, refresh],
  );

  return { data, error, actionError, busy, realtime, refresh, act };
}
