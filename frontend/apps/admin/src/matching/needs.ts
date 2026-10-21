import { type components } from "@tutortrack/api-client";

/** Gap G5c (FR-19-1): the students' needs in a match search, and shared helpers. */
export type MatchNeeds = components["schemas"]["MatchNeeds"];
export type NeedsOverride = {
  exam_boards: string[];
  sen_tags: string[];
  gender: "" | components["schemas"]["TutorGenderEnum"];
};

export const GENDERS = ["female", "male", "non_binary"] as const;

/** Split a comma-separated list typed by staff into trimmed labels. */
export function splitTags(value: string): string[] {
  return value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}
