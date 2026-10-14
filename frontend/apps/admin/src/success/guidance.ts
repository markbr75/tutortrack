import { unwrap } from "@tutortrack/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";

export const GUIDANCE_KEY = ["me", "guidance"] as const;

/** What the help layer needs on every page (tours, unread counts, NPS, analytics). */
export function useGuidance(enabled = true) {
  return useQuery({
    queryKey: GUIDANCE_KEY,
    queryFn: async () => unwrap(await api.GET("/api/v1/me/guidance")),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useTourStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      key,
      status,
    }: {
      key: string;
      status: "completed" | "dismissed" | "restart";
    }) =>
      unwrap(
        await api.POST("/api/v1/me/guidance/tours/{key}", {
          params: { path: { key } },
          body: { status },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(GUIDANCE_KEY, data),
  });
}
