/** Runtime configuration (Vite env). Domain data never lives here — it comes from the backend. */
const DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1";
const DEFAULT_STUDENT_APP_URL = "http://localhost:5173/";

export const config = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL as string | undefined) || DEFAULT_API_BASE_URL,
  /** The Student web app — where "Who are you? → Student" on the sign-in page leads. */
  studentAppUrl:
    (import.meta.env.VITE_STUDENT_APP_URL as string | undefined) || DEFAULT_STUDENT_APP_URL,
} as const;
