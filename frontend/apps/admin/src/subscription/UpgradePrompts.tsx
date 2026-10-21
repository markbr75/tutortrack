import { useTranslation } from "@tutortrack/i18n";
import { Button, buttonClass } from "@tutortrack/ui";
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
    <div className="rounded-xl border border-border bg-surface px-5 py-4 text-sm">
      <p className="font-semibold">{t(`plan.features.${feature}`)}</p>
      <p className="mt-0.5 text-muted-foreground">
        {t("plan.lockedBody", { plan: planName(t, requiredPlan) })}
      </p>
      <Link
        to={PLAN_PAGE}
        className="mt-2 inline-block font-medium text-link underline-offset-2 hover:underline"
      >
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
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-xl border border-border bg-surface text-foreground backdrop:bg-black/40"
    >
      <div className="space-y-3 px-5 py-4">
        <h2 id="upgrade-title" className="text-base font-semibold">
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
      </div>
      <div className="flex flex-wrap justify-end gap-2 border-t border-rule px-5 py-3">
        <Button variant="ghost" onClick={dismissUpgrade}>
          {t("common.close")}
        </Button>
        <Link to={PLAN_PAGE} onClick={dismissUpgrade} className={buttonClass()}>
          {t("plan.seePlans")}
        </Link>
      </div>
    </dialog>
  );
}
