/**
 * Shared HTTP state per backend resource. Each resource is requested by ONE hook instance
 * at the top of the dashboard and handed to every panel that shows it.
 *
 * Feature 14: the interval is adjustable — while the WebSocket is live, pushed events
 * update the data (`mutate`) and REST only re-syncs occasionally; when it is down, the
 * caller passes the fallback interval. `refresh` re-fetches once (e.g. after reconnecting).
 */
import { useCallback, useEffect, useRef, useState } from "react";

export interface Polled<T> {
  data: T | null;
  error: string | null;
  /** Wall-clock time of the last successful response. */
  updatedAt: number | null;
  refresh: () => Promise<void>;
  /** Apply a pushed backend update to the current data (never invents values). */
  mutate: (update: (prev: T | null) => T | null) => void;
}

export function usePoll<T>(load: () => Promise<T>, intervalMs: number | null): Polled<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const alive = useRef(true);
  const refresh = useCallback(async () => {
    try {
      const d = await load();
      if (!alive.current) return;
      setData(d);
      setError(null);
      setUpdatedAt(Date.now());
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e)); // keep last data
    }
  }, [load]);
  useEffect(() => {
    alive.current = true;
    const first = setTimeout(() => void refresh(), 0); // initial REST state
    return () => {
      alive.current = false;
      clearTimeout(first);
    };
  }, [refresh]);
  useEffect(() => {
    if (intervalMs === null) return;
    const id = setInterval(() => void refresh(), intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);
  const mutate = useCallback((update: (prev: T | null) => T | null) => setData(update), []);
  return { data, error, updatedAt, refresh, mutate };
}
