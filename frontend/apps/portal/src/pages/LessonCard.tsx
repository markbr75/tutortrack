import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  RegisterMark,
  registerMarkFor,
  SelectField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, usePortalMe } from "../api";
import { JoinButton } from "../JoinButton";

export type PortalLesson = components["schemas"]["PortalLesson"];

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
  const [mode, setMode] = useState<"none" | "cancel" | "absence" | "move">("none");
  const [newStart, setNewStart] = useState("");
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

  const move = useMutation({
    mutationFn: async () => {
      const begin = new Date(newStart);
      const length = new Date(lesson.end).getTime() - new Date(lesson.start).getTime();
      return unwrap(
        await api.POST("/api/v1/portal/lessons/{lesson_id}/reschedule", {
          ...path,
          body: {
            options: [
              {
                start: begin.toISOString(),
                end: new Date(begin.getTime() + length).toISOString(),
              },
            ],
            reason,
          },
        }),
      );
    },
    onSuccess: done,
  });

  const clock = (iso: string) =>
    formatDateTime(iso, i18n.language, undefined, { hour: "2-digit", minute: "2-digit" });
  const start = new Date(lesson.start);
  const future = start.getTime() > Date.now() && lesson.status === "planned";
  // Gap G3: lessons booked online can only be cancelled online until the booking window.
  const cancelUntil = lesson.cancel_online_until ? new Date(lesson.cancel_online_until) : null;
  const tooLate = cancelUntil !== null && cancelUntil.getTime() <= Date.now();
  const features = me.data?.features;

  return (
    <article
      className="space-y-3 rounded-xl border border-border bg-surface p-4"
      aria-label={lesson.title}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-muted-foreground">
            {formatDateTime(lesson.start, i18n.language, undefined, {
              weekday: "long",
              day: "numeric",
              month: "long",
            })}
            {lesson.status !== "planned" ? ` · ${t(`portal.status.${lesson.status}`)}` : ""}
          </p>
          <p className="text-xl font-semibold tabular-nums">
            <time dateTime={lesson.start}>{clock(lesson.start)}</time>–
            <time dateTime={lesson.end}>{clock(lesson.end)}</time>
          </p>
        </div>
        <RegisterMark
          kind={registerMarkFor(lesson.status, lesson.end)}
          label={t(`portal.status.${lesson.status}`)}
          className="mt-1 size-5"
        />
      </div>
      <div className="space-y-1">
        <h2 className="font-semibold">{lesson.title}</h2>
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
      </div>
      {/* Most useful first; cancelling is last and quietest. Two even columns on phones. */}
      <div className="grid grid-cols-2 gap-2 border-t border-rule pt-3 sm:flex sm:flex-wrap">
        {lesson.online && lesson.status === "planned" ? (
          <JoinButton
            url={lesson.join_url || lesson.meeting_url}
            start={lesson.start}
            end={lesson.end}
            opensAt={lesson.join_opens_at}
            className="col-span-2"
          />
        ) : null}
        {lesson.online && lesson.status === "planned" ? (
          <Link
            to="/classroom/$lessonId"
            params={{ lessonId: lesson.id }}
            className={buttonClass({ variant: "secondary" })}
          >
            {t("classroom.open")}
          </Link>
        ) : null}
        {actions && future && features?.reschedule && mode === "none" ? (
          <Button variant="secondary" onClick={() => setMode("move")}>
            {t("portalBooking.askToMove")}
          </Button>
        ) : null}
        {actions && future && features?.absence && mode === "none" ? (
          <Button variant="secondary" onClick={() => setMode("absence")}>
            {t("portal.reportAbsence")}
          </Button>
        ) : null}
        <a
          className={buttonClass({ variant: "secondary" })}
          href={`/api/v1/portal/lessons/${lesson.id}/ics`}
        >
          {t("portal.addToCalendar")}
        </a>
        {actions && future && features?.cancellations && mode === "none" && !tooLate ? (
          <Button
            variant="ghost"
            className="text-muted-foreground"
            onClick={() => {
              setMode("cancel");
              preview.mutate();
            }}
          >
            {t("portal.cancel")}
          </Button>
        ) : null}
        {actions && future && features?.cancellations && mode === "none" && tooLate ? (
          <span className="col-span-2 self-center text-xs text-muted-foreground">
            {t("g3.portal.cancelClosed")}
          </span>
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
          {cancelUntil && !tooLate ? (
            <p className="text-xs text-muted-foreground">
              {t("g3.portal.cancelUntil", {
                when: formatDateTime(cancelUntil.toISOString(), i18n.language),
              })}
            </p>
          ) : null}
          {preview.error || cancel.error ? (
            <Alert tone="danger">{(preview.error ?? cancel.error)?.message}</Alert>
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
      {mode === "move" ? (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            move.mutate();
          }}
        >
          <TextField
            label={t("portalBooking.newTime")}
            type="datetime-local"
            required
            value={newStart}
            onChange={(e) => setNewStart(e.target.value)}
          />
          <TextField
            label={t("portal.reason")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">{t("portalBooking.moveHelp")}</p>
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={move.isPending || !newStart}>
              {t("portalBooking.sendRequest")}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setMode("none")}>
              {t("portal.keep")}
            </Button>
          </div>
        </form>
      ) : null}
      {move.isSuccess ? <Alert tone="success">{t("portalBooking.requestSent")}</Alert> : null}
      {cancel.error || absence.error || move.error ? (
        <Alert tone="danger">{(cancel.error ?? absence.error ?? move.error)?.message}</Alert>
      ) : null}
    </article>
  );
}
