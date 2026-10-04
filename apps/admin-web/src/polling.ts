/** Live views poll this fast only when no real-time socket exists (legacy behaviour). */
export const POLL_MS = 3_000;
/** Feature 14: WebSocket down → slower REST polling of live data. */
export const FALLBACK_POLL_MS = 10_000;
/** Feature 14: WebSocket live → occasional safety re-sync over REST. */
export const RESYNC_MS = 60_000;
/** Routes / schedule change slowly (trip status, aggregates). */
export const SLOW_POLL_MS = 15_000;
/** Analytics are aggregates — refreshed less often. */
export const ANALYTICS_POLL_MS = 20_000;
