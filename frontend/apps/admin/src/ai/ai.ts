import { ApiError, unwrap, type components } from "@tutortrack/api-client";
import { useQuery } from "@tanstack/react-query";

import { api, usePermission } from "../api";

export type AiFeature = components["schemas"]["AIFeatureEnum"];
export type AiProposal = components["schemas"]["AIProposal"];

/** Whether the plan includes AI and which features the organisation turned on (E31). */
export function useAiStatus(enabled = true) {
  return useQuery({
    queryKey: ["ai", "status"],
    staleTime: 60_000,
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/v1/ai/status")),
  });
}

/** `useAiFeature("inbox")`: show AI controls only when the plan, the organisation's opt-in
 * and the person's `ai.use` permission all allow it. */
export function useAiFeature(feature: AiFeature): boolean {
  const canUse = usePermission("ai.use");
  const status = useAiStatus(canUse);
  return Boolean(canUse && status.data?.available && status.data.features[feature]);
}

const MESSAGES: Record<string, string> = {
  "ai-credits-exhausted": "ai.errors.credits",
  "ai-rate-limited": "ai.errors.rate",
  "ai-refused": "ai.errors.refused",
  "ai-unavailable": "ai.errors.unavailable",
  "ai-provider-error": "ai.errors.unavailable",
  "ai-incomplete": "ai.errors.incomplete",
  "feature-disabled": "ai.errors.disabled",
};

/** A friendly message for an AI request that failed (RFC 7807 problem types). */
export function aiError(t: (key: string) => string, error: unknown): string {
  if (error instanceof ApiError) {
    const key = MESSAGES[error.code];
    if (key) return t(key);
    return error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

/** Records that a person used a draft on a record: it is then shown as AI-assisted. */
export async function markAssisted(request: string, subjectType: string, subjectId: string) {
  return unwrap(
    await api.POST("/api/v1/ai/assists", {
      body: { request, subject_type: subjectType, subject_id: subjectId },
    }),
  );
}
