import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePortalMe } from "../api";

export type PortalLesson = components["schemas"]["PortalLesson"];

const JOIN_EARLY_MS = 10 * 60_000;

/** One lesson for families: when, who, where, join link, add to calendar, and
 * cancel or report an absence with the policy shown first (FR-15-3/4). */
export function LessonCard({
  lesson,
  actions = true,
}: {
  lesson: PortalLesson;
  actions?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const me = usePortalMe();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"none" | "cancel" | "absence">("none");
  const [reason, setReason] = useState("");
  const [student, setStudent] = useState(lesson.students[0]?.id ?? "");
  const path = { params: { path: { lesson_id: lesson.id } } };
  const preview = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/portal/lessons/{lesson_id}/cancel", {
          ...path,
          params: { ...path.params, query: { preview: true } },
          body: { reason: "" },
        }),
      ),
  });
  const done = () => {
    setMode("none");
    void queryClient.invalidateQueries({ queryKey: ["portal"] });
  };
  const cancel = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/portal/lessons/{lesson_id}/cancel", { ...path, body: { reason } }),
      ),
    onSuccess: done,
  });
  const absence = useMutation({
    mutationFn: async () =>
      api
        .POST("/api/v1/portal/lessons/{lesson_id}/absence", {
          ...path,
          body: { student, note: reason },
        })
        .then(unwrap),
    onSuccess: done,
  });

  const start = new Date(lesson.start);
  const joinable =
    lesson.online &&
    lesson.meeting_url &&
    Date.now() >= start.getTime() - JOIN_EARLY_MS &&
    Date.now() < new Date(lesson.end).getTime();
  const future = start.getTime() > Date.now() && lesson.status === "planned";
  const features = me.data?.features;

  return (
    <article className="space-y-2 rounded-lg border border-border p-4" aria-label={lesson.title}>
      <h3 className="font-semibold">{lesson.title}</h3>
      <p className="text-sm">
        {formatDateTime(lesson.start, i18n.language)}
        {lesson.status !== "planned" ? ` · ${t(`portal.status.${lesson.status}`)}` : ""}
      </p>
      <p className="text-sm text-muted-foreground">
        {lesson.tutors.map((tutor) => tutor.name).join(", ")}
        {lesson.online
          ? ` · ${t("portal.online")}`
          : lesson.location
            ? ` · ${lesson.location}`
            : ""}
      </p>
      {lesson.tutors.some((tutor) => tutor.email || tutor.phone) ? (
        <p className="text-xs text-muted-foreground">
          {lesson.tutors.map((tutor) => [tutor.email, tutor.phone].filter(Boolean).join(" · "))}
        </p>
      ) : null}
      {lesson.notes_for_client ? <p className="text-sm">{lesson.notes_for_client}</p> : null}
      <div className="flex flex-wrap gap-2 text-sm">
        {joinable ? (
          <a
            className="rounded-md bg-primary px-3 py-1.5 text-primary-foreground"
            href={lesson.meeting_url}
          >
            {t("portal.join")}
          </a>
        ) : null}
        <a
          className="rounded-md border border-border px-3 py-1.5"
          href={`/api/v1/portal/lessons/${lesson.id}/ics`}
        >
          {t("portal.addToCalendar")}
        </a>
        {actions && future && features?.cancellations && mode === "none" ? (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setMode("cancel");
              preview.mutate();
            }}
          >
            {t("portal.cancel")}
          </Button>
        ) : null}
        {actions && future && features?.absence && mode === "none" ? (
          <Button size="sm" variant="ghost" onClick={() => setMode("absence")}>
            {t("portal.reportAbsence")}
          </Button>
        ) : null}
      </div>
      {mode === "cancel" ? (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            cancel.mutate();
          }}
        >
          {preview.data ? (
            <Alert tone={preview.data.kind === "late" ? "warning" : "info"}>
              {preview.data.message}
            </Alert>
          ) : null}
          <TextField
            label={t("portal.reason")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex gap-2">
            <Button type="submit" variant="danger" size="sm" disabled={cancel.isPending}>
              {t("portal.confirmCancel")}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setMode("none")}>
              {t("portal.keep")}
            </Button>
          </div>
        </form>
      ) : null}
      {mode === "absence" ? (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            absence.mutate();
          }}
        >
          {lesson.students.length > 1 ? (
            <SelectField
              label={t("portal.whoIsAbsent")}
              value={student}
              onChange={(e) => setStudent(e.target.value)}
              options={lesson.students.map((s) => ({ value: s.id, label: s.name }))}
            />
          ) : null}
          <TextField
            label={t("portal.note")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">{t("portal.absenceHelp")}</p>
          <Button type="submit" size="sm" disabled={absence.isPending}>
            {t("portal.sendAbsence")}
          </Button>
        </form>
      ) : null}
      {cancel.error || absence.error ? (
        <Alert tone="danger">{(cancel.error ?? absence.error)?.message}</Alert>
      ) : null}
    </article>
  );
}
