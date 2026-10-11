import { ApiError, unwrap } from "@tutortrack/api-client";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : String(error ?? "");
}

export function fieldErrors(error: unknown): Record<string, string[]> {
  if (!(error instanceof ApiError)) return {};
  const problem = error.problem as { errors?: Record<string, string[]> } | undefined;
  return problem?.errors ?? {};
}

export function useBrandingOptions() {
  return useQuery({
    queryKey: ["branding-options"],
    queryFn: async () => unwrap(await api.GET("/api/v1/branding/options")),
    staleTime: 5 * 60_000,
  });
}
