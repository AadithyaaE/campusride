/** One authenticated `/ws` connection for the dashboard (Feature 14). */
import { useEffect, useRef } from "react";

import type { AdminApi } from "../api/client";
import { RealtimeClient, type RealtimeStatus, type WsEnvelope } from "./client";

export interface RealtimeHandlers {
  onEvent: (e: WsEnvelope) => void;
  /** Re-fetch authoritative REST state (after every (re)connection). */
  onOpen: (reconnect: boolean) => void;
  onStatus: (s: RealtimeStatus) => void;
}

export function useRealtime(api: AdminApi, handlers: RealtimeHandlers): void {
  const latest = useRef(handlers);
  useEffect(() => {
    latest.current = handlers;
  });
  useEffect(() => {
    const client = new RealtimeClient({
      url: api.realtimeUrl(),
      getToken: () => api.token(),
      onEvent: (e) => latest.current.onEvent(e),
      onOpen: (r) => latest.current.onOpen(r),
      onStatus: (s) => latest.current.onStatus(s),
      onUnauthorized: () => api.unauthorized(), // refused session → sign out (same as REST 401)
    });
    client.start();
    return () => client.stop();
  }, [api]);
}
