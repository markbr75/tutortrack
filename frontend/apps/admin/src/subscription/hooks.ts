import { unwrap, type components } from "@tutortrack/api-client";
import { useQuery } from "@tanstack/react-query";

import { api, usePermission } from "../api";

export type Subscription = components["schemas"]["Subscription"];
export type Plan = components["schemas"]["Plan"];
export type Usage = components["schemas"]["Usage"];
export type ChangePreview = components["schemas"]["ChangePreview"];
export type CreditAccount = components["schemas"]["CreditAccount"];

export const PLAN_PAGE = "/settings/plan";

/** What the organisation's plan includes (E04 FR-04-2). */
export function useEntitlements() {
  return useQuery({
    queryKey: ["entitlements"],
    queryFn: async () => unwrap(await api.GET("/api/v1/entitlements")),
    staleTime: 60_000,
  });
}

/**
 * `useEntitlement("payroll")`: whether the plan includes a feature, and the cheapest plan
 * that does. While loading it reports enabled, so nothing flickers locked.
 */
export function useEntitlement(key: string): { enabled: boolean; requiredPlan: string | null } {
  const { data } = useEntitlements();
  if (!data) return { enabled: true, requiredPlan: null };
  return {
    enabled: data.features[key] ?? false,
    requiredPlan: data.required_plans[key] ?? null,
  };
}

export function useSubscription() {
  const canView = usePermission("subscription.view");
  return useQuery({
    queryKey: ["subscription"],
    queryFn: async () => unwrap(await api.GET("/api/v1/subscription")),
    enabled: canView,
    retry: false,
  });
}

/** Whole days until `iso` (never negative). */
export function daysUntil(iso: string | null | undefined, now: Date = new Date()): number {
  if (!iso) return 0;
  return Math.max(0, Math.ceil((new Date(iso).getTime() - now.getTime()) / 86_400_000));
}

export {
  dismissUpgrade,
  reportUpgradeRequired,
  upgradeOf,
  useUpgradeProblem,
  type UpgradeProblem,
} from "./upgradeStore";
