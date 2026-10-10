import { useTranslation } from "@tutortrack/i18n";
import { Alert } from "@tutortrack/ui";
import { Link } from "@tanstack/react-router";

import { PLAN_PAGE, daysUntil, useSubscription } from "./hooks";

/** Trial ending, payment failed or read-only: shown to whoever can see the plan (FR-04-6). */
export function SubscriptionBanner() {
  const { t } = useTranslation();
  const { data: sub } = useSubscription();
  if (!sub) return null;
  let message: string | null = null;
  let tone: "info" | "warning" = "warning";
  if (sub.status === "past_due") message = t("plan.banner.pastDue");
  else if (sub.status === "suspended" || sub.status === "cancelled") {
    message = t("plan.banner.locked");
  } else if (sub.status === "trialing" && !sub.has_payment_method) {
    const days = daysUntil(sub.trial_ends_at);
    if (days <= 7) {
      message = t("plan.banner.trialEnding", { count: days });
      tone = "info";
    }
  }
  if (!message) return null;
  return (
    <Alert tone={tone} className="mb-6 flex flex-wrap items-center justify-between gap-2">
      <span>{message}</span>
      <Link to={PLAN_PAGE} className="font-medium underline">
        {t("plan.banner.action")}
      </Link>
    </Alert>
  );
}
