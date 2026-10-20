import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";
import { JoinButton } from "../JoinButton";
import { isNetworkError, isOffline, queueChange, useOutbox } from "../offline/client";
import { ClassroomLink, TutorRecordings, VideoRegisterHint } from "./Phase3";
import { MoveLessonForm, PreviousReport } from "./Planning";
import { CheckInButtons, TutorRaiseConcern } from "./SafeguardingTools";
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
  const [moving, setMoving] = useState(false);
  const [reason, setReason] = useState("");

  const queued = useOutbox().filter((item) => item.lessonId === lessonId);
  const completedOffline = queued.some((item) => item.kind === "lesson.complete");

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["tutor"] });
  };
  const writeOffline = () =>
    void navigate({ to: "/tutor/lessons/$lessonId/report", params: { lessonId } });
  const openReport = useMutation({
    mutationFn: async () => {
      if (isOffline()) return null;
      try {
        return unwrap(
          await api.POST("/api/v1/lessons/{lesson_id}/reports", {
            params: { path: { lesson_id: lessonId } },
            body: {},
          }),
        );
      } catch (error) {
        if (isNetworkError(error)) return null;
        throw error;
      }
    },
    onSuccess: (report) =>
      report
        ? void navigate({ to: "/tutor/reports/$reportId", params: { reportId: report.id } })
        : writeOffline(),
  });
  // Without a signal the register is kept on the phone and synced later (E16-T08); the
  // same Idempotency-Key makes a retry of a request that did arrive harmless.
  const complete = useMutation({
    mutationFn: async (): Promise<"done" | "queued"> => {
      const body = {
        attendance: (lesson.data?.attendees ?? []).map((a) => ({
          attendee: a.id,
          outcome: outcomes[a.id] ?? "present",
          late_minutes:
            (outcomes[a.id] ?? "present") === "late" && late[a.id] ? Number(late[a.id]) : null,
        })),
        actual_start: null,
        actual_end: null,
        override_balance: false,
      };
      const key = crypto.randomUUID();
      const queue = async () => {
        await queueChange(
          {
            kind: "lesson.complete",
            label: lesson.data?.title ?? "",
            lessonId,
            reportId: null,
            body,
            etag: null,
          },
          key,
        );
        return "queued" as const;
      };
      if (isOffline()) return queue();
      try {
        unwrap(
          await api.POST("/api/v1/lessons/{id}/complete", {
            ...path,
            body,
            headers: { "Idempotency-Key": key },
          }),
        );
        return "done";
      } catch (error) {
        if (isNetworkError(error)) return queue();
        throw error;
      }
    },
    onSuccess: (outcome) => {
      if (outcome === "queued") {
        writeOffline();
        return;
      }
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

  if (lesson.isPending) return <Spinner label={t("grid.loading")} />;
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
      <PreviousReport lessonId={lessonId} />
      {l.online && planned ? <HostJoin lesson={l} /> : null}
      {l.online && planned ? <ClassroomLink lessonId={lessonId} /> : null}
      {completedOffline ? (
        <Alert>
          {t("pwa.completedOffline")}{" "}
          <button type="button" className="underline" onClick={writeOffline}>
            {t("tutor.writeReport")}
          </button>
        </Alert>
      ) : null}

      {planned && started && !completedOffline ? (
        <form
          className="space-y-3"
          aria-label={t("tutor.register")}
          onSubmit={(e) => {
            e.preventDefault();
            complete.mutate();
          }}
        >
          <h2 className="font-semibold">{t("tutor.register")}</h2>
          {l.online ? (
            <VideoRegisterHint
              lessonId={lessonId}
              onApply={(s) => {
                const next: Record<string, Outcome> = {};
                const minutes: Record<string, string> = {};
                for (const row of s.students) {
                  next[row.attendee_id] = row.suggested_outcome as Outcome;
                  if (row.late_minutes) minutes[row.attendee_id] = String(row.late_minutes);
                }
                setOutcomes((o) => ({ ...o, ...next }));
                setLate((v) => ({ ...v, ...minutes }));
              }}
            />
          ) : null}
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
      {planned && !started && !moving ? (
        <Button variant="secondary" onClick={() => setMoving(true)}>
          {me.data?.can_reschedule ? t("tutorPlan.move") : t("tutorPlan.askToMove")}
        </Button>
      ) : null}
      {moving ? (
        <MoveLessonForm
          lesson={l}
          onDone={() => {
            setMoving(false);
            void lesson.refetch();
          }}
        />
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
      {l.online ? <TutorRecordings lessonId={lessonId} /> : null}
      <CheckInButtons lessonId={lessonId} online={Boolean(l.online)} />
      <TutorRaiseConcern
        lessonId={lessonId}
        studentId={l.attendees.length === 1 ? l.attendees[0]?.student : null}
      />
    </article>
  );
}

/** The tutor's host link from `/lessons/{id}/join` (E22-T09). */
function HostJoin({ lesson }: { lesson: { id: string; start: string; end: string } }) {
  const join = useQuery({
    queryKey: ["tutor", "lesson", lesson.id, "join"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/lessons/{id}/join", {
        params: { path: { id: lesson.id } },
      });
      return data ?? null;
    },
  });
  if (!join.data) return null;
  return (
    <div>
      <JoinButton
        url={join.data.url}
        start={lesson.start}
        end={lesson.end}
        opensAt={join.data.opens_at}
      />
    </div>
  );
}
