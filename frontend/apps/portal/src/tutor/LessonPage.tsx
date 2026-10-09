import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";
import { useTutorMe } from "./useTutorMe";

type Outcome = components["schemas"]["AttendanceOutcomeEnum"];
const OUTCOMES: Outcome[] = ["present", "late", "absent_notified", "no_show"];

/** A lesson: details, the 30-second complete flow (register → report) and cancelling
 * (E16-T03). */
export function LessonPage({ lessonId }: { lessonId: string }) {
  const { t, i18n } = useTranslation();
  const me = useTutorMe();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const path = { params: { path: { id: lessonId } } };
  const lesson = useQuery({
    queryKey: ["tutor", "lesson", lessonId],
    queryFn: async () => unwrap(await api.GET("/api/v1/lessons/{id}", path)),
  });
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});
  const [late, setLate] = useState<Record<string, string>>({});
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["tutor"] });
  };
  const openReport = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/lessons/{lesson_id}/reports", {
          params: { path: { lesson_id: lessonId } },
          body: {},
        }),
      ),
    onSuccess: (report) =>
      void navigate({ to: "/tutor/reports/$reportId", params: { reportId: report.id } }),
  });
  const complete = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/lessons/{id}/complete", {
          ...path,
          body: {
            attendance: (lesson.data?.attendees ?? []).map((a) => ({
              attendee: a.id,
              outcome: outcomes[a.id] ?? "present",
              late_minutes:
                (outcomes[a.id] ?? "present") === "late" && late[a.id] ? Number(late[a.id]) : null,
            })),
            actual_start: null,
            actual_end: null,
            override_balance: false,
          },
        }),
      ),
    onSuccess: () => {
      refresh();
      openReport.mutate();
    },
  });
  const cancel = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/lessons/{id}/cancel", {
          ...path,
          body: { cancelled_by: "tutor", reason, notify: true, scope: "this", override: null },
        }),
      ),
    onSuccess: () => {
      setCancelling(false);
      refresh();
      void lesson.refetch();
    },
  });

  if (lesson.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  const l = lesson.data;
  if (!l) return <Alert tone="danger">{t("errors.generic")}</Alert>;
  const started = new Date(l.start).getTime() <= Date.now();
  const planned = l.status === "planned";

  return (
    <article className="space-y-4">
      <header>
        <h1 className="text-xl font-semibold">{l.title}</h1>
        <p className="text-sm text-muted-foreground">
          {formatDateTime(l.start, i18n.language)} · {t(`portal.status.${l.status}`)}
        </p>
      </header>
      {l.notes_for_tutor ? <Alert>{l.notes_for_tutor}</Alert> : null}
      {l.online && l.meeting_url ? (
        <a
          className="inline-block rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground"
          href={l.meeting_url}
        >
          {t("portal.join")}
        </a>
      ) : null}

      {planned && started ? (
        <form
          className="space-y-3"
          aria-label={t("tutor.register")}
          onSubmit={(e) => {
            e.preventDefault();
            complete.mutate();
          }}
        >
          <h2 className="font-semibold">{t("tutor.register")}</h2>
          {l.attendees.map((a) => (
            <div key={a.id} className="flex flex-wrap items-end gap-2">
              <SelectField
                label={t("tutor.attendanceFor", { name: a.name })}
                value={outcomes[a.id] ?? (a.outcome || "present")}
                onChange={(e) => setOutcomes((o) => ({ ...o, [a.id]: e.target.value as Outcome }))}
                options={OUTCOMES.map((o) => ({ value: o, label: t(`tutor.outcome.${o}`) }))}
              />
              {(outcomes[a.id] ?? "present") === "late" ? (
                <TextField
                  className="w-24"
                  type="number"
                  min={0}
                  label={t("tutor.minutesLate")}
                  value={late[a.id] ?? ""}
                  onChange={(e) => setLate((v) => ({ ...v, [a.id]: e.target.value }))}
                />
              ) : null}
            </div>
          ))}
          <Button type="submit" disabled={complete.isPending}>
            {t("tutor.completeAndReport")}
          </Button>
        </form>
      ) : null}
      {l.status === "completed" ? (
        <Button onClick={() => openReport.mutate()} disabled={openReport.isPending}>
          {t("tutor.writeReport")}
        </Button>
      ) : null}
      {planned && me.data?.can_cancel && !cancelling ? (
        <Button variant="ghost" onClick={() => setCancelling(true)}>
          {t("tutor.cancelLesson")}
        </Button>
      ) : null}
      {cancelling ? (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            cancel.mutate();
          }}
        >
          <TextField
            label={t("portal.reason")}
            required
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">{t("tutor.cancelHelp")}</p>
          <Button type="submit" variant="danger" disabled={cancel.isPending}>
            {t("portal.confirmCancel")}
          </Button>
        </form>
      ) : null}
      {complete.error || cancel.error || openReport.error ? (
        <Alert tone="danger">{(complete.error ?? cancel.error ?? openReport.error)?.message}</Alert>
      ) : null}
    </article>
  );
}
