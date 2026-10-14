import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId } from "react";

import { api, usePermission } from "../api";
import { track } from "./analytics";

const KEY = ["setup-checklist"] as const;

/**
 * First steps on the dashboard (E30 FR-30-5): set up a service, add a student, schedule a
 * lesson, connect Stripe and send the first invoice. Steps tick themselves when done
 * anywhere in the app; managers can hide the list.
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
      className="mt-6 rounded-lg border border-border p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={titleId} className="text-lg font-medium">
          {t("setupChecklist.title")}
        </h2>
        {canHide ? (
          <Button size="sm" variant="ghost" loading={hide.isPending} onClick={() => hide.mutate()}>
            {t("setupChecklist.hide")}
          </Button>
        ) : null}
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        {t("setupChecklist.progress", { done: data.done, total: data.total })}
      </p>
      <div
        role="progressbar"
        aria-label={t("setupChecklist.title")}
        aria-valuemin={0}
        aria-valuemax={data.total}
        aria-valuenow={data.done}
        className="mt-2 h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className="h-full bg-brand motion-safe:transition-[width]"
          style={{ width: `${(data.done / Math.max(1, data.total)) * 100}%` }}
        />
      </div>
      <ol className="mt-4 space-y-2">
        {data.steps.map((step) => (
          <li key={step.key} className="flex items-center gap-3 text-sm">
            <span
              aria-hidden="true"
              className={
                step.done
                  ? "grid size-5 place-items-center rounded-full bg-brand text-xs text-brand-foreground"
                  : "size-5 rounded-full border border-border"
              }
            >
              {step.done ? "✓" : ""}
            </span>
            {step.done ? (
              <span className="text-muted-foreground line-through">
                {t(`setupChecklist.steps.${step.key}`)}
                <span className="sr-only"> ({t("setupChecklist.done")})</span>
              </span>
            ) : (
              <Link to={step.link as "/"} className="underline">
                {t(`setupChecklist.steps.${step.key}`)}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
