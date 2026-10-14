import { unwrap } from "@tutortrack/api-client";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export type AiFeature = "lesson_report" | "content";

/** Whether the organisation turned an AI feature on (E31); the API enforces the rest. */
export function useAiFeature(feature: AiFeature): boolean {
  const status = useQuery({
    queryKey: ["ai", "status"],
    staleTime: 60_000,
    retry: false,
    queryFn: async () => unwrap(await api.GET("/api/v1/ai/status")),
  });
  return Boolean(status.data?.available && status.data.features[feature]);
}

/** Marks the report as AI-assisted once the tutor submits a report built from a draft. */
export async function markReportAssisted(request: string, reportId: string) {
  return unwrap(
    await api.POST("/api/v1/ai/assists", {
      body: { request, subject_type: "lesson_report", subject_id: reportId },
    }),
  );
}
