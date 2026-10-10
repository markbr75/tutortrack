import { ApiError } from "@tutortrack/api-client";
import { useSyncExternalStore } from "react";

/** The open upgrade prompt (one at a time), fed by failed mutations. */

export interface UpgradeProblem {
  feature?: string;
  limit?: string;
  allowed?: number;
  required_plan?: string;
  detail: string;
}

let current: UpgradeProblem | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

/** The problem behind an `upgrade-required` error, if that's what `error` is. */
export function upgradeOf(error: unknown): UpgradeProblem | null {
  if (!(error instanceof ApiError) || error.code !== "upgrade-required") return null;
  const p = error.problem as unknown as Record<string, unknown>;
  return {
    feature: p.feature as string | undefined,
    limit: p.limit as string | undefined,
    allowed: p.allowed as number | undefined,
    required_plan: p.required_plan as string | undefined,
    detail: error.message,
  };
}

/** Called for every failed mutation (see `createQueryClient`): opens the upgrade dialog. */
export function reportUpgradeRequired(error: unknown): void {
  const problem = upgradeOf(error);
  if (!problem) return;
  current = problem;
  emit();
}

export function dismissUpgrade(): void {
  current = null;
  emit();
}

export function useUpgradeProblem(): UpgradeProblem | null {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => current,
  );
}
