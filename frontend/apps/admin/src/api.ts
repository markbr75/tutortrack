import { ApiError, createApiClient, unwrap } from "@tutortrack/api-client";
import { QueryClient, useQuery } from "@tanstack/react-query";

/** Same-origin in every environment (Vite proxies /api in development). */
export const api = createApiClient();

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Never retry client errors (401/403/404/422): only transient failures.
        retry: (failureCount, error) =>
          !(error instanceof ApiError && error.status < 500) && failureCount < 2,
      },
    },
  });
}

/**
 * Session bootstrap. E03 replaces this with `GET /api/v1/me`; until then the features
 * endpoint doubles as an authenticated "who am I in this organisation" probe.
 */
export function useFeatures() {
  return useQuery({
    queryKey: ["features"],
    queryFn: async () => unwrap(await api.GET("/api/v1/features")).features,
  });
}

/** `useFeature("courses")` gates UI behind a feature flag / plan entitlement. */
export function useFeature(key: string): boolean {
  const { data } = useFeatures();
  return Boolean(data?.[key]);
}

export function isAuthError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}
