import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, ErrorFallback, PageHeader, RegisterMark, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";

/** FR-09-8: past lessons still planned, with bulk complete/cancel and a tutor nudge. */
export function UnconfirmedPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canComplete = usePermission("scheduling.lesson.complete");
  const canCancel = usePermission("scheduling.lesson.cancel");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState("");
  const lessons = useQuery({
    queryKey: ["unconfirmed-lessons"],
    queryFn: async () => unwrap(await api.GET("/api/v1/unconfirmed-lessons")),
  });
  const rows = lessons.data ?? [];
  const ids = [...selected];

  const act = useMutation({
    mutationFn: async (kind: "complete" | "cancel" | "nudge") => {
      if (kind === "nudge") {
        const out = unwrap(await api.POST("/api/v1/unconfirmed-lessons", { body: { ids } }));
        return t("delivery.unconfirmed.nudged", { count: out.nudged });
      }
      const out = unwrap(
        await api.POST("/api/v1/lessons/bulk", {
          body: { action: kind, ids, reason: "", cancelled_by: "admin" },
        }),
      );
      return t("delivery.unconfirmed.result", {
        ok: out.succeeded.length,
        failed: Object.keys(out.failed).length,
      });
    },
    onSuccess: (text) => {
      setMessage(text);
      setSelected(new Set());
      void queryClient.invalidateQueries({ queryKey: ["unconfirmed-lessons"] });
    },
  });

  const toggle = (id: string, on: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const allChosen = rows.length > 0 && selected.size === rows.length;
  return (
    <div>
      <PageHeader
        title={t("delivery.unconfirmed.title")}
        description={t("delivery.unconfirmed.help")}
      />
      {message ? (
        <Alert tone="success" className="mb-4">
          {message}
        </Alert>
      ) : null}
      <ErrorList error={act.error} />
      {lessons.isPending ? (
        <Spinner label={t("grid.loading")} />
      ) : lessons.isError ? (
        <ErrorFallback
          title={t("errors.generic")}
          retryLabel={t("errors.retry")}
          onRetry={() => void lessons.refetch()}
        />
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("delivery.unconfirmed.empty")}</p>
      ) : (
        <section
          aria-label={t("delivery.unconfirmed.title")}
          className="rounded-xl border border-border bg-surface"
        >
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border px-4 py-3">
            <label className="flex items-center gap-3 text-sm">
              <input
                type="checkbox"
                className="size-4"
                aria-label={t("delivery.unconfirmed.selectAll")}
                checked={allChosen}
                onChange={(e) =>
                  setSelected(e.target.checked ? new Set(rows.map((r) => r.id)) : new Set())
                }
              />
              <span aria-live="polite" className="text-muted-foreground">
                {ids.length
                  ? t("designS5.delivery.chosen", { count: ids.length })
                  : t("designS5.delivery.waiting", { count: rows.length })}
              </span>
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={!ids.length}
                onClick={() => act.mutate("nudge")}
              >
                {t("delivery.unconfirmed.nudge")}
              </Button>
              {canCancel ? (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={!ids.length}
                  onClick={() => act.mutate("cancel")}
                >
                  {t("delivery.unconfirmed.cancel")}
                </Button>
              ) : null}
              {canComplete ? (
                <Button
                  size="sm"
                  disabled={!ids.length}
                  loading={act.isPending}
                  onClick={() => act.mutate("complete")}
                >
                  {t("delivery.unconfirmed.complete")}
                </Button>
              ) : null}
            </div>
          </div>
          <div
            role="region"
            aria-label={t("designS5.delivery.lessonsTable")}
            tabIndex={0}
            className="overflow-x-auto"
          >
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border">
                <tr>
                  <th scope="col" className="w-10 px-4 py-2.5">
                    <span className="sr-only">{t("delivery.unconfirmed.selectAll")}</span>
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    {t("delivery.reports.lesson")}
                  </th>
                  <th scope="col" className="px-4 py-2.5 max-sm:hidden">
                    {t("calendar.tutors")}
                  </th>
                  <th scope="col" className="w-20 px-4 py-2.5 text-center">
                    {t("home.register.mark")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((lesson) => {
                  const tutors = lesson.tutors.map((x) => x.name).join(", ");
                  return (
                    <tr
                      key={lesson.id}
                      className="border-t border-rule first:border-0 has-[:checked]:bg-muted/60"
                    >
                      <td className="px-4 py-2.5">
                        <input
                          type="checkbox"
                          className="size-4"
                          aria-label={t("delivery.unconfirmed.select", { title: lesson.title })}
                          checked={selected.has(lesson.id)}
                          onChange={(e) => toggle(lesson.id, e.target.checked)}
                        />
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="font-medium">{lesson.title}</span>
                        <span className="block text-xs text-muted-foreground tabular-nums">
                          <time dateTime={lesson.start}>
                            {formatDateTime(lesson.start, i18n.language)}
                          </time>
                          <span className="sm:hidden">{tutors ? ` · ${tutors}` : ""}</span>
                        </span>
                      </td>
                      <td className="px-4 py-2.5 max-sm:hidden">{tutors}</td>
                      <td className="px-4 py-2.5">
                        <RegisterMark
                          kind="due"
                          label={t("home.register.marks.due")}
                          className="mx-auto"
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
