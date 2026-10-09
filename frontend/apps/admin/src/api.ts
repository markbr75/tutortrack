import { ApiError, createApiClient, unwrap, type components } from "@tutortrack/api-client";
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

export type Me = components["schemas"]["Me"];

/** Session bootstrap: who am I here (user, organisation, role, permissions, features). */
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me")),
  });
}

/** Feature flags for the current organisation (from `/me`). */
export function useFeatures() {
  const me = useMe();
  return { ...me, data: me.data?.features };
}

/** `useFeature("courses")` gates UI behind a feature flag / plan entitlement. */
export function useFeature(key: string): boolean {
  const { data } = useMe();
  return Boolean(data?.features[key]);
}

/** `usePermission("team.invite")`: whether the current user holds a permission here. */
export function usePermission(codename: string): boolean {
  const { data } = useMe();
  return Boolean(data?.permissions[codename]);
}

/** Only allow same-site relative paths as post-login destinations. */
export function safeNext(value: string | null | undefined): string {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

export function isAuthError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

export type Organisation = components["schemas"]["Organisation"];
export type MyOrganisation = components["schemas"]["MyOrganisation"];
export type OnboardingState = components["schemas"]["OnboardingState"];

/** The current organisation (profile, status for the suspended banner, branding). */
export function useOrganisation() {
  return useQuery({
    queryKey: ["organisation"],
    queryFn: async () => unwrap(await api.GET("/api/v1/organisation")),
  });
}

/** Organisations the user belongs to, for the switcher (FR-02-7). */
export function useMyOrganisations() {
  return useQuery({
    queryKey: ["me", "organisations"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/organisations")),
  });
}

export interface Term {
  singular: string;
  plural: string;
}

/** Tenant terminology ("Tutor" -> "Teacher"); falls back to the default words. */
export function useTerminology(): Record<string, Term> | undefined {
  const { data } = useQuery({
    queryKey: ["settings", "general"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/settings/{area}", { params: { path: { area: "general" } } })),
    retry: false,
  });
  return data?.values["general.terminology"] as Record<string, Term> | undefined;
}

/** Field errors from a validation/business-rule problem, keyed by field name. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  const errors = (error.problem.errors ?? {}) as Record<string, unknown>;
  return Object.fromEntries(
    Object.entries(errors).map(([key, value]) => [
      key,
      Array.isArray(value) ? String(value[0]) : String(value),
    ]),
  );
}
