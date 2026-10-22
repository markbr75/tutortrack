import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";
import { useId } from "react";

import { api, usePermission } from "../api";
import { track } from "./analytics";

const KEY = ["setup-checklist"] as const;

/**
 * First steps on the dashboard (E30 FR-30-5): set up a service, add a student, schedule a
 * lesson, connect Stripe and send the first invoice. Steps tick themselves when done
 * anywhere in the app; managers can hide the list. Progress is said in words, never a bar.
 */
export function SetupChecklist() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const titleId = useId();
  const canHide = usePermission("success.checklist.manage");
  const checklist = useQuery({
    queryKey: KEY,
    queryFn: async () => unwrap(await api.GET("/api/v1/setup-checklist")),
    retry: false,
  });
  const hide = useMutation({
    mutationFn: async () =>
      unwrap(await api.PATCH("/api/v1/setup-checklist", { body: { dismissed: true } })),
    onSuccess: (data) => {
      track("setup_checklist.hidden");
      queryClient.setQueryData(KEY, data);
    },
  });
  const data = checklist.data;
  if (!data || data.dismissed_at || data.completed_at) return null;
  return (
    <section
      aria-labelledby={titleId}
      data-tour="setup-checklist"
      className="mt-6 rounded-xl border border-border bg-surface"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-border px-5 py-3.5">
        <h2 id={titleId} className="text-base font-semibold">
          {t("setupChecklist.title")}
        </h2>
        <p className="text-sm text-muted-foreground tabular-nums">
          {t("setupChecklist.progress", { done: data.done, total: data.total })}
        </p>
      </div>
      <ol className="divide-y divide-rule">
        {data.steps.map((step) => (
          <li key={step.key} className="flex items-center gap-3 px-5 py-2.5 text-sm">
            {step.done ? (
              <Check aria-hidden="true" className="size-4 shrink-0" strokeWidth={2.2} />
            ) : (
              <span
                aria-hidden="true"
                className="size-4 shrink-0 rounded-full border border-field"
              />
            )}
            {step.done ? (
              <span className="text-muted-foreground line-through">
                {t(`setupChecklist.steps.${step.key}`)}
                <span className="sr-only"> ({t("setupChecklist.done")})</span>
              </span>
            ) : (
              <Link
                to={step.link as "/"}
                className="font-medium text-link underline-offset-2 hover:underline"
              >
                {t(`setupChecklist.steps.${step.key}`)}
              </Link>
            )}
          </li>
        ))}
      </ol>
      {canHide ? (
        <div className="border-t border-rule px-5 py-3">
          <Button
            size="sm"
            variant="ghost"
            className="-ml-3 text-muted-foreground"
            loading={hide.isPending}
            onClick={() => hide.mutate()}
          >
            {t("setupChecklist.hide")}
          </Button>
        </div>
      ) : null}
    </section>
  );
}
