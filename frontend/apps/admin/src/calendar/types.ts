import { ApiError, type components } from "@tutortrack/api-client";

export type CalendarItem = components["schemas"]["CalendarItem"];
export type Conflict = components["schemas"]["Conflict"];

export function conflictsOf(error: unknown): Conflict[] {
  if (!(error instanceof ApiError)) return [];
  return ((error.problem as { conflicts?: Conflict[] }).conflicts ?? []).filter(
    (c) => c.severity === "hard",
  );
}
