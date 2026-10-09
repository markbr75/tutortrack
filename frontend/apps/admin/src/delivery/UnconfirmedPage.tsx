import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner } from "@tutortrack/ui";
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

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold">{t("delivery.unconfirmed.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("delivery.unconfirmed.help")}</p>
      </header>
      {message ? <Alert tone="success">{message}</Alert> : null}
      <ErrorList error={act.error} />
      {lessons.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("delivery.unconfirmed.empty")}</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {canComplete ? (
              <Button size="sm" disabled={!ids.length} onClick={() => act.mutate("complete")}>
                {t("delivery.unconfirmed.complete")}
              </Button>
            ) : null}
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
            <Button
              size="sm"
              variant="secondary"
              disabled={!ids.length}
              onClick={() => act.mutate("nudge")}
            >
              {t("delivery.unconfirmed.nudge")}
            </Button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="py-2 pr-2">
                    <input
                      type="checkbox"
                      className="size-4"
                      aria-label={t("delivery.unconfirmed.selectAll")}
                      checked={selected.size === rows.length}
                      onChange={(e) =>
                        setSelected(e.target.checked ? new Set(rows.map((r) => r.id)) : new Set())
                      }
                    />
                  </th>
                  <th scope="col" className="py-2 pr-4">
                    {t("delivery.reports.lesson")}
                  </th>
                  <th scope="col" className="py-2 pr-4">
                    {t("calendar.tutors")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((lesson) => (
                  <tr key={lesson.id} className="border-b border-border">
                    <td className="py-2 pr-2">
                      <input
                        type="checkbox"
                        className="size-4"
                        aria-label={t("delivery.unconfirmed.select", { title: lesson.title })}
                        checked={selected.has(lesson.id)}
                        onChange={(e) => toggle(lesson.id, e.target.checked)}
                      />
                    </td>
                    <td className="py-2 pr-4">
                      {lesson.title}
                      <span className="block text-muted-foreground">
                        {formatDateTime(lesson.start, i18n.language)}
                      </span>
                    </td>
                    <td className="py-2 pr-4">{lesson.tutors.map((x) => x.name).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
