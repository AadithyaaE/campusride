import { useEffect, useState } from "react";

import { useApi } from "../api/ApiContext";
import type { HealthOut } from "../api/types";
import { config } from "../config";

export interface HealthState {
  /** null until the first check completes. */
  reachable: boolean | null;
  health: HealthOut | null;
}

/** Polls the public `GET /health` endpoint for the header status and backend clock. */
export function useHealth(intervalMs: number = config.healthPollMs): HealthState {
  const api = useApi();
  const [state, setState] = useState<HealthState>({ reachable: null, health: null });

  useEffect(() => {
    let cancelled = false;
    const check = () =>
      api.health().then(
        (health) => !cancelled && setState({ reachable: true, health }),
        () => !cancelled && setState((s) => ({ reachable: false, health: s.health })),
      );
    void check();
    const id = setInterval(check, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [api, intervalMs]);

  return state;
}
