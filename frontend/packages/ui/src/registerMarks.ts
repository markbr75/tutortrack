/**
 * The register's marks for a lesson: one vocabulary wherever lesson state appears.
 * completed = an ink tick; missed = a red ring; cancelled = a struck ring; due = a red dashed
 * ring (over, still to be marked); upcoming = a pale dashed ring (still to come).
 */
export type RegisterMarkKind = "completed" | "missed" | "cancelled" | "due" | "upcoming";

/** Which mark a lesson carries: its status, and whether it is already over. */
export function registerMarkFor(
  status: string,
  end: string,
  now: Date = new Date(),
): RegisterMarkKind {
  if (status === "completed") return "completed";
  if (status === "missed") return "missed";
  if (status === "cancelled") return "cancelled";
  return new Date(end) <= now ? "due" : "upcoming";
}
