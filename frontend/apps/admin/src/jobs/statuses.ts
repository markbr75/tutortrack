export const JOB_STATUSES = [
  "draft",
  "seeking_tutor",
  "active",
  "paused",
  "completed",
  "cancelled",
] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

/** Allowed moves, mirroring the server's status machine (E07 FR-07-4). */
export const NEXT_STATUSES: Record<JobStatus, JobStatus[]> = {
  draft: ["seeking_tutor", "active", "cancelled"],
  seeking_tutor: ["draft", "active", "cancelled"],
  active: ["seeking_tutor", "paused", "completed", "cancelled"],
  paused: ["active", "completed", "cancelled"],
  completed: ["active"],
  cancelled: [],
};

export const BOARD_STATUSES: JobStatus[] = ["draft", "seeking_tutor", "active", "paused"];

export const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6] as const;
