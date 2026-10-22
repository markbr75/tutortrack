import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PanelFooter,
  RegisterMark,
  registerMarkFor,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import { JoinButton } from "../JoinButton";
import { PortalHeader, Word } from "../layout/PortalPage";
import { isNetworkError, isOffline, queueChange, useOutbox } from "../offline/client";
import { ClassroomLink, TutorRecordings, VideoRegisterHint } from "./Phase3";
import { MoveLessonForm, PreviousReport } from "./Planning";
import { CheckInButtons, TutorRaiseConcern } from "./SafeguardingTools";
import { useTutorMe } from "./useTutorMe";

type Outcome = components["schemas"]["AttendanceOutcomeEnum"];
const OUTCOMES: Outcome[] = ["present", "late", "absent_notified", "no_show"];

const quiet = "text-muted-foreground hover:text-foreground";

/** The register mark an attendance choice gives: a tick for present or late, a ring for an
 * absence. */
function outcomeMark(outcome: Outcome): "completed" | "missed" {
  return outcome === "present" || outcome === "late" ? "completed" : "missed";
}

/** A lesson: details, the 30-second complete flow (register → report) and cancelling
 * (E16-T03). Laid out as a record: the way back to Lessons, the title, one line of when and
 * the status in words, then the register as the work area. */
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
  const reasonRef = useRef<HTMLInputElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const wasCancelling = useRef(false);
  useEffect(() => {
    if (cancelling) reasonRef.current?.focus();
    else if (wasCancelling.current) cancelButton.current?.focus();
    wasCancelling.current = cancelling;
  }, [cancelling]);

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
  const mark = registerMarkFor(l.status, l.end);
  const canMove = planned && !started && !moving;
  const canCancel = planned && me.data?.can_cancel && !cancelling;

  return (
    <article aria-labelledby="lesson-title">
      <PortalHeader
        titleId="lesson-title"
        back={<Link to="/tutor/schedule">{t("tutor.nav.schedule")}</Link>}
        title={l.title}
        description={
          <span className="inline-flex flex-wrap items-center gap-x-1.5">
            <span className="tabular-nums">{formatDateTime(l.start, i18n.language)}</span>
            <span aria-hidden="true">·</span>
            {mark === "due" ? (
              <Word tone="margin">{t("designS10.toMark")}</Word>
            ) : (
              <Word className="text-foreground">{t(`portal.status.${l.status}`)}</Word>
            )}
          </span>
        }
        actions={
          canMove || canCancel ? (
            <>
              {canMove ? (
                <Button size="sm" variant="secondary" onClick={() => setMoving(true)}>
                  {me.data?.can_reschedule ? t("tutorPlan.move") : t("tutorPlan.askToMove")}
                </Button>
              ) : null}
              {canCancel ? (
                <Button
                  ref={cancelButton}
                  size="sm"
                  variant="ghost"
                  className={quiet}
                  onClick={() => setCancelling(true)}
                >
                  {t("tutor.cancelLesson")}
                </Button>
              ) : null}
            </>
          ) : null
        }
      />
      <div className="space-y-6">
        {cancelling ? (
          <form
            aria-label={t("tutor.cancelLesson")}
            onSubmit={(e) => {
              e.preventDefault();
              cancel.mutate();
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") setCancelling(false);
            }}
          >
            <RuledPanel title={t("tutor.cancelLesson")} description={t("tutor.cancelHelp")} flush>
              <div className="px-5 py-4">
                <TextField
                  ref={reasonRef}
                  label={t("portal.reason")}
                  required
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </div>
              <PanelFooter>
                <Button type="submit" variant="danger" disabled={cancel.isPending}>
                  {t("portal.confirmCancel")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  className={quiet}
                  onClick={() => setCancelling(false)}
                >
                  {t("portal.keep")}
                </Button>
              </PanelFooter>
            </RuledPanel>
          </form>
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
        {l.notes_for_tutor ? <Alert>{l.notes_for_tutor}</Alert> : null}
        {l.online && planned ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <HostJoin lesson={l} />
            <ClassroomLink lessonId={lessonId} />
          </div>
        ) : null}
        {completedOffline ? (
          <Alert>
            {t("pwa.completedOffline")}{" "}
            <button
              type="button"
              className="font-medium text-link underline-offset-2 hover:underline"
              onClick={writeOffline}
            >
              {t("tutor.writeReport")}
            </button>
          </Alert>
        ) : null}

        {planned && started && !completedOffline ? (
          <form
            aria-label={t("tutor.register")}
            onSubmit={(e) => {
              e.preventDefault();
              complete.mutate();
            }}
          >
            <RuledPanel title={t("tutor.register")} rule="margin" flush>
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
              <ul className="divide-y divide-rule">
                {l.attendees.map((a) => {
                  const outcome = outcomes[a.id] ?? ((a.outcome || "present") as Outcome);
                  return (
                    <li
                      key={a.id}
                      className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 px-5 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto]"
                    >
                      <span className="font-medium">{a.name}</span>
                      <span className="flex w-14 justify-center sm:order-last sm:w-20">
                        <RegisterMark
                          kind={outcomeMark(outcome)}
                          label={t(`tutor.outcome.${outcome}`)}
                        />
                      </span>
                      <div className="col-span-2 flex flex-wrap items-end gap-2 sm:col-span-1">
                        <SelectField
                          size="sm"
                          hideLabel
                          label={t("tutor.attendanceFor", { name: a.name })}
                          value={outcome}
                          onChange={(e) =>
                            setOutcomes((o) => ({ ...o, [a.id]: e.target.value as Outcome }))
                          }
                          options={OUTCOMES.map((o) => ({
                            value: o,
                            label: t(`tutor.outcome.${o}`),
                          }))}
                        />
                        {outcome === "late" ? (
                          <span className="flex items-center gap-2">
                            <TextField
                              size="sm"
                              className="w-20 text-right tabular-nums"
                              type="number"
                              min={0}
                              label={t("tutor.minutesLate")}
                              hideLabel
                              value={late[a.id] ?? ""}
                              onChange={(e) => setLate((v) => ({ ...v, [a.id]: e.target.value }))}
                            />
                            <span aria-hidden="true" className="text-sm text-muted-foreground">
                              {t("designS10.minutesLateUnit")}
                            </span>
                          </span>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ul>
              <PanelFooter>
                <Button type="submit" disabled={complete.isPending}>
                  {t("tutor.completeAndReport")}
                </Button>
              </PanelFooter>
            </RuledPanel>
          </form>
        ) : null}
        {l.status === "completed" ? (
          <div>
            <Button onClick={() => openReport.mutate()} disabled={openReport.isPending}>
              {t("tutor.writeReport")}
            </Button>
          </div>
        ) : null}
        {complete.error || cancel.error || openReport.error ? (
          <Alert tone="danger">
            {(complete.error ?? cancel.error ?? openReport.error)?.message}
          </Alert>
        ) : null}
        <PreviousReport lessonId={lessonId} />
        {l.online ? <TutorRecordings lessonId={lessonId} /> : null}
        <CheckInButtons lessonId={lessonId} online={Boolean(l.online)} />
        <TutorRaiseConcern
          lessonId={lessonId}
          studentId={l.attendees.length === 1 ? l.attendees[0]?.student : null}
        />
      </div>
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
    <JoinButton
      url={join.data.url}
      start={lesson.start}
      end={lesson.end}
      opensAt={join.data.opens_at}
    />
  );
}
