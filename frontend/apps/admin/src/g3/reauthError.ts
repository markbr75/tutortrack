import { ApiError } from "@tutortrack/api-client";

/** True when the API asks the person to confirm it's them first (gap G3 step-up). */
export function needsReauth(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 403 &&
    String((error.problem as { type?: string }).type ?? "").endsWith("reauthentication-required")
  );
}
