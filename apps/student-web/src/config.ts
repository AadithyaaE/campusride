/** Runtime configuration (Vite env). Domain data never lives here — it comes from the backend. */

const DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1";
const DEFAULT_ADMIN_APP_URL = "http://localhost:5174/";

export const config = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL as string | undefined) || DEFAULT_API_BASE_URL,
  /** The Admin web app — where "Who are you? → Admin" on the sign-in page leads. */
  adminAppUrl: (import.meta.env.VITE_ADMIN_APP_URL as string | undefined) || DEFAULT_ADMIN_APP_URL,
  /** How often the header re-checks backend reachability (ms). */
  healthPollMs: 15_000,
  /** OpenStreetMap raster tiles (no API key). */
  tileUrl: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  tileAttribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
} as const;
