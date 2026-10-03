import { ApiError, BackendUnavailableError, MalformedResponseError } from "../api/client";
import { config } from "../config";

/** Human-readable title + detail for any error the API client can raise. */
export function describeError(error: Error): { title: string; detail: string } {
  if (error instanceof BackendUnavailableError) {
    return {
      title: "Backend unreachable",
      detail: `${error.message} Expected at ${config.apiBaseUrl}.`,
    };
  }
  if (error instanceof MalformedResponseError) {
    return {
      title: "Unexpected backend response",
      detail: `${error.message} The frontend and backend contracts may be out of sync (run npm run gen:api).`,
    };
  }
  if (error instanceof ApiError) {
    if (error.status === 404) return { title: "Not found", detail: error.message };
    return { title: `Request failed (${error.code})`, detail: error.message };
  }
  return { title: "Something went wrong", detail: error.message };
}
