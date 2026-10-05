/** Short, driver-friendly messages for backend errors (never stack traces). */
import { ApiError } from "../api/client";

/** Shown on the sign-in screen after a forced sign-out (401 / refused WebSocket session). */
export const SESSION_ENDED = "Your session has ended. Please sign in again.";

const BY_CODE: Record<string, string> = {
  backend_unavailable: "Connection unavailable",
  unauthorized: SESSION_ENDED,
  forbidden: "This app is for drivers only.",
  invalid_driver: "No driver profile is linked to this account.",
  no_assignment: "You have no bus assigned. Please contact the transport office.",
  no_trip: "No more trips are scheduled for your bus today.",
  trip_already_active: "A trip is already active on your bus.",
  trip_completed: "This trip is already completed.",
  no_active_trip: "There is no active trip to stop.",
  schedule_controlled: "Your bus runs on the automatic demo schedule.",
  gps_unavailable: "No trip is running, so there is no GPS to simulate.",
  unavailable: "The trip system is unavailable right now. Please try again.",
};

export function friendlyError(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return BY_CODE[e.code] ?? fallback;
  return fallback;
}
