/**
 * Live fleet state from the BACKEND (synthetic simulator → telemetry → tracking)
 * and the backend's stop matching for the signed-in student.
 *
 * Lightweight POLLING of `GET /buses`, `GET /students/me/arrivals` (matching +
 * backend ETA), `GET /students/me/bus-options` (backend multi-bus comparison) and
 * `GET /sim/status` every few seconds —
 * the WebSocket feed replaces this later. The browser never computes bus
 * positions; it only displays what the backend reports.
 */
import { useCallback, useEffect, useState } from "react";

import { useApi } from "../api/ApiContext";
import type { BusOptionsOut, BusOut, MyArrivalsOut, SimStatusOut } from "../api/types";

export const POLL_MS = 3_000;

export interface LiveFleet {
  buses: BusOut[] | null;
  /** Backend matching + ETAs for the student's boarding stop (assigned bus + others). */
  arrivals: MyArrivalsOut | null;
  /** Backend comparison of the buses serving the boarding stop (indicators, crowding). */
  options: BusOptionsOut | null;
  sim: SimStatusOut | null;
  error: Error | null;
  /** Wall-clock time of the last successful poll. */
  fetchedAt: Date | null;
  refresh: () => Promise<void>;
  control: {
    start: () => Promise<void>;
    pause: () => Promise<void>;
    reset: () => Promise<void>;
    setSpeed: (speed: number) => Promise<void>;
  };
}

export function useLiveFleet(pollMs: number = POLL_MS): LiveFleet {
  const api = useApi();
  const [buses, setBuses] = useState<BusOut[] | null>(null);
  const [arrivals, setArrivals] = useState<MyArrivalsOut | null>(null);
  const [options, setOptions] = useState<BusOptionsOut | null>(null);
  const [sim, setSim] = useState<SimStatusOut | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [b, a, o, s] = await Promise.all([
        api.listBuses(),
        api.myArrivals(),
        api.myBusOptions(),
        api.simStatus(),
      ]);
      setBuses(b);
      setArrivals(a);
      setOptions(o);
      setSim(s);
      setError(null);
      setFetchedAt(new Date());
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    }
  }, [api]);

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      if (!cancelled) void refresh();
    };
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, pollMs);
    return () => {
      cancelled = true;
      clearTimeout(first);
      clearInterval(id);
    };
  }, [refresh, pollMs]);

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
    sim,
    error,
    fetchedAt,
    refresh,
    control: {
      start: act(() => api.simStart()),
      pause: act(() => api.simPause()),
      reset: act(() => api.simReset()),
      setSpeed: (speed: number) => act(() => api.simSetSpeed(speed))(),
    },
  };
}
