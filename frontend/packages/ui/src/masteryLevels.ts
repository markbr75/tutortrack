export type MasteryLevel = "not_started" | "learning" | "secure" | "mastered";

/** Topic mastery levels, lowest first (E21). */
export const MASTERY_LEVELS: ReadonlyArray<MasteryLevel> = [
  "not_started",
  "learning",
  "secure",
  "mastered",
];
