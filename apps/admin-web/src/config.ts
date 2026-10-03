/** Runtime configuration (Vite env). Domain data never lives here — it comes from the backend. */
const DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1";

export const config = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL as string | undefined) || DEFAULT_API_BASE_URL,
} as const;
