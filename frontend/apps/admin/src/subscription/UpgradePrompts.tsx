import { useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, type ReactNode } from "react";

import { PLAN_PAGE, dismissUpgrade, useEntitlement, useUpgradeProblem } from "./hooks";

function planName(t: (key: string) => string, key: string | null | undefined): string {
  return key ? t(`plan.names.${key}`) : t("plan.names.enterprise");
}

/**
 * Shows `children` when the plan includes `feature`; otherwise a short explanation with an
 * upgrade link, so locked features stay discoverable (FR-04-2).
 */
export function Locked({ feature, children }: { feature: string; children: ReactNode }) {
  const { t } = useTranslation();
  const { enabled, requiredPlan } = useEntitlement(feature);
  if (enabled) return <>{children}</>;
  return (
    <div className="rounded-md border border-dashed border-border p-4 text-sm">
      <p className="font-medium">{t(`plan.features.${feature}`)}</p>
      <p className="mt-1 text-muted-foreground">
        {t("plan.lockedBody", { plan: planName(t, requiredPlan) })}
      </p>
      <Link to={PLAN_PAGE} className="mt-2 inline-block font-medium underline">
        {t("plan.seePlans")}
      </Link>
    </div>
  );
}

/** Opens whenever an action fails with `upgrade-required` (mounted once in the shell). */
export function UpgradeDialog() {
  const { t } = useTranslation();
  const problem = useUpgradeProblem();
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (problem && !dialog.open) dialog.showModal();
    if (!problem && dialog.open) dialog.close();
  }, [problem]);
  if (!problem) return null;
  return (
    <dialog
      ref={ref}
      onClose={dismissUpgrade}
      aria-labelledby="upgrade-title"
      className="w-full max-w-md rounded-lg border border-border bg-background p-5 shadow-lg backdrop:bg-black/40"
    >
      <div className="space-y-3">
        <h2 id="upgrade-title" className="text-lg font-semibold">
          {t("plan.upgradeTitle", { plan: planName(t, problem.required_plan) })}
        </h2>
        <p className="text-sm">
          {problem.limit
            ? t("plan.limitReached", {
                what: t(`plan.limits.${problem.limit}`),
                allowed: problem.allowed ?? 0,
              })
            : t("plan.featureMissing", {
                feature: t(`plan.features.${problem.feature ?? ""}`),
              })}
        </p>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={dismissUpgrade}>
            {t("common.close")}
          </Button>
          <Link
            to={PLAN_PAGE}
            onClick={dismissUpgrade}
            className="inline-flex items-center rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-foreground"
          >
            {t("plan.seePlans")}
          </Link>
        </div>
      </div>
    </dialog>
  );
}
