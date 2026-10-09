import { ApiError, createApiClient, unwrap, type components } from "@tutortrack/api-client";
import { QueryClient, useQuery } from "@tanstack/react-query";

export const api = createApiClient();

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      },
    },
  });
}

export type PortalMe = components["schemas"]["PortalMe"];

/** Who the signed-in family member is (household, features, branding). */
export function usePortalMe() {
  return useQuery({
    queryKey: ["portal", "me"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/me")),
  });
}

export function problemStatus(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null;
}
