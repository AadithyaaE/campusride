import { ApiError, BackendUnavailableError, MalformedResponseError } from "../api/client";
import { config } from "../config";

/**
 * Short, human title + detail for any error the API client can raise. Technical detail
 * (URL, contract hints) goes to the developer console, never to the student.
 */
export function describeError(error: Error): { title: string; detail: string } {
  if (error instanceof BackendUnavailableError) {
    console.warn(`CampusRide API unreachable at ${config.apiBaseUrl}:`, error.message);
    return {
      title: "Can't reach CampusRide",
      detail: "Check your internet connection. We'll keep showing the latest information we have.",
    };
  }
  if (error instanceof MalformedResponseError) {
    console.warn(
      "Unexpected API response (frontend/backend contract out of sync?):",
      error.message,
    );
    return { title: "Something didn't load correctly", detail: "Please try again in a moment." };
  }
  if (error instanceof ApiError) {
    if (error.status === 404) return { title: "Not found", detail: error.message };
    return { title: "Couldn't load this right now", detail: error.message };
  }
  return {
    title: "Something went wrong",
    detail: error.message || "Please try again in a moment.",
  };
}
