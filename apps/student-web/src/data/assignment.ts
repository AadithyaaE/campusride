import { useCallback } from "react";

import { useApi } from "../api/ApiContext";
import { useAsync } from "../hooks/useAsync";

/** The signed-in student's college-assigned bus, from `GET /students/me/assignment`. */
export function useMyAssignment() {
  const api = useApi();
  const load = useCallback(() => api.myAssignment(), [api]);
  return useAsync(load, "my-assignment");
}
