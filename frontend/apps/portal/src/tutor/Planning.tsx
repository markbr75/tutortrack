import { ApiError, unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";
import { useTutorMe } from "./useTutorMe";

type Conflict = components["schemas"]["Conflict"];

/** `datetime-local` value (browser time) + minutes → ISO start and end. */
function span(local: string, minutes: number): { start: string; end: string } | null {
  if (!local) return null;
  const start = new Date(local);
  if (Number.isNaN(start.getTime())) return null;
  return {
    start: start.toISOString(),
    end: new Date(start.getTime() + minutes * 60_000).toISOString(),
  };
}

function problemConflicts(error: unknown): Conflict[] {
  if (!(error instanceof ApiError)) return [];
  const conflicts = (error.problem as { conflicts?: Conflict[] }).conflicts;
  return Array.isArray(conflicts) ? conflicts : [];
}

/** Conflict feedback (FR-16-2): hard clashes stop the change, soft ones are warnings. */
export function ConflictList({ conflicts }: { conflicts: Conflict[] }) {
  const { t } = useTranslation();
  if (!conflicts.length) return null;
  const hard = conflicts.some((c) => c.severity === "hard");
  return (
    <Alert tone={hard ? "danger" : "warning"}>
      <p className="font-medium">{hard ? t("tutorPlan.clash") : t("tutorPlan.warnings")}</p>
      <ul className="list-disc pl-5">
        {conflicts.map((c, i) => (
          <li key={`${c.kind}-${i}`}>{c.message}</li>
        ))}
      </ul>
    </Alert>
  );
}

function CheckResult({ conflicts }: { conflicts: Conflict[] | undefined }) {
  const { t } = useTranslation();
  if (!conflicts) return null;
  if (!conflicts.length)
    return (
      <p role="status" className="text-sm text-muted-foreground">
        {t("tutorPlan.noClash")}
      </p>
    );
  return (
    <div role="status">
      <ConflictList conflicts={conflicts} />
    </div>
  );
}

/** Book a lesson on one of the tutor's jobs (needs "tutors can create lessons"). */
export function PlanLessonForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const jobs = useQuery({
    queryKey: ["tutor", "jobs"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tutor/jobs")),
  });
  const [job, setJob] = useState("");
  const [when, setWhen] = useState("");
  const [minutes, setMinutes] = useState("");
  const chosen = jobs.data?.find((j) => j.id === job);
  const duration = Number(minutes || chosen?.duration_minutes || 60);
  const times = span(when, duration);
  const check = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/tutor/lessons/check", { body: { job, ...times! } })),
  });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/tutor/lessons", {
          body: { job, ...times!, notes_for_tutor: "" },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tutor"] });
      onDone();
    },
  });
  if (jobs.isPending) return <Spinner className="size-5" label={t("grid.loading")} />;
  if (!jobs.data?.length) return <p className="text-sm">{t("tutorPlan.noJobs")}</p>;
  return (
    <form
      className="space-y-3 rounded-md border border-border p-3"
      aria-label={t("tutorPlan.newLesson")}
      onSubmit={(e) => {
        e.preventDefault();
        if (times) create.mutate();
      }}
    >
      <h2 className="font-semibold">{t("tutorPlan.newLesson")}</h2>
      <SelectField
        label={t("tutorPlan.job")}
        required
        value={job}
        onChange={(e) => {
          setJob(e.target.value);
          check.reset();
        }}
        options={[
          { value: "", label: "—" },
          ...jobs.data.map((j) => ({
            value: j.id,
            label: `${j.name} · ${j.students.map((s) => s.name).join(", ")}`,
          })),
        ]}
      />
      <div className="flex flex-wrap gap-3">
        <TextField
          type="datetime-local"
          step={300}
          required
          label={t("tutorPlan.when")}
          value={when}
          onChange={(e) => {
            setWhen(e.target.value);
            check.reset();
          }}
        />
        <TextField
          className="w-28"
          type="number"
          min={5}
          step={5}
          label={t("tutorPlan.minutes")}
          value={minutes || String(chosen?.duration_minutes ?? "")}
          onChange={(e) => setMinutes(e.target.value)}
        />
      </div>
      <CheckResult conflicts={check.data} />
      <ConflictList conflicts={problemConflicts(create.error)} />
      {create.error && !problemConflicts(create.error).length ? (
        <Alert tone="danger">{create.error.message}</Alert>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="secondary"
          disabled={!job || !times || check.isPending}
          onClick={() => check.mutate()}
        >
          {t("tutorPlan.check")}
        </Button>
        <Button type="submit" disabled={!job || !times || create.isPending}>
          {t("tutorPlan.book")}
        </Button>
      </div>
    </form>
  );
}

/** Move a lesson: directly when the organisation lets tutors reschedule, otherwise a
 * reschedule request to the office (FR-16-2, FR-08-8). */
export function MoveLessonForm({
  lesson,
  onDone,
}: {
  lesson: { id: string; start: string; end: string };
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const me = useTutorMe();
  const queryClient = useQueryClient();
  const [when, setWhen] = useState("");
  const [reason, setReason] = useState("");
  const minutes = Math.round((Date.parse(lesson.end) - Date.parse(lesson.start)) / 60_000);
  const times = span(when, minutes);
  const direct = Boolean(me.data?.can_reschedule);
  const check = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/tutor/lessons/check", { body: { lesson: lesson.id, ...times! } }),
      ),
  });
  const move = useMutation({
    mutationFn: async () => {
      if (direct) {
        unwrap(
          await api.POST("/api/v1/tutor/lessons/{lesson_id}/move", {
            params: { path: { lesson_id: lesson.id } },
            body: { ...times!, reason },
          }),
        );
        return "moved" as const;
      }
      unwrap(
        await api.POST("/api/v1/lessons/{lesson_id}/reschedule-requests", {
          params: { path: { lesson_id: lesson.id } },
          body: { options: [times!], reason },
        }),
      );
      return "asked" as const;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tutor"] });
    },
  });
  if (move.data) {
    return (
      <Alert tone="success">
        {move.data === "moved" ? t("tutorPlan.moved") : t("tutorPlan.asked")}{" "}
        <button type="button" className="underline" onClick={onDone}>
          {t("tutorPlan.close")}
        </button>
      </Alert>
    );
  }
  return (
    <form
      className="space-y-3 rounded-md border border-border p-3"
      aria-label={direct ? t("tutorPlan.move") : t("tutorPlan.askToMove")}
      onSubmit={(e) => {
        e.preventDefault();
        if (times) move.mutate();
      }}
    >
      <h2 className="font-semibold">{direct ? t("tutorPlan.move") : t("tutorPlan.askToMove")}</h2>
      {!direct ? <p className="text-sm text-muted-foreground">{t("tutorPlan.askHelp")}</p> : null}
      <TextField
        type="datetime-local"
        step={300}
        required
        label={t("tutorPlan.newTime")}
        value={when}
        onChange={(e) => {
          setWhen(e.target.value);
          check.reset();
        }}
      />
      <TextField
        label={t("tutorPlan.reason")}
        value={reason}
        required={!direct}
        onChange={(e) => setReason(e.target.value)}
      />
      <CheckResult conflicts={check.data} />
      <ConflictList conflicts={problemConflicts(move.error)} />
      {move.error && !problemConflicts(move.error).length ? (
        <Alert tone="danger">{move.error.message}</Alert>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="secondary"
          disabled={!times || check.isPending}
          onClick={() => check.mutate()}
        >
          {t("tutorPlan.check")}
        </Button>
        <Button type="submit" disabled={!times || move.isPending}>
          {direct ? t("tutorPlan.moveNow") : t("tutorPlan.sendRequest")}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          {t("tutorPlan.close")}
        </Button>
      </div>
    </form>
  );
}

function answerText(value: unknown): string {
  if (Array.isArray(value)) return value.map(answerText).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** The latest earlier report for this lesson's student(s) (FR-16-3). */
export function PreviousReport({ lessonId }: { lessonId: string }) {
  const { t, i18n } = useTranslation();
  const previous = useQuery({
    queryKey: ["tutor", "lesson", lessonId, "previous-report"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutor/lessons/{lesson_id}/previous-report", {
          params: { path: { lesson_id: lessonId } },
        }),
      ),
  });
  const report = previous.data?.report;
  if (!report) return null;
  return (
    <details className="rounded-md border border-border p-3">
      <summary className="cursor-pointer font-medium">
        {t("previousReport.title", {
          when: formatDateTime(report.lesson_start, i18n.language),
        })}
      </summary>
      <p className="mt-1 text-xs text-muted-foreground">
        {report.lesson_title} · {report.tutor}
      </p>
      <dl className="mt-2 space-y-2 text-sm">
        {report.answers.map((a) => (
          <div key={a.key}>
            <dt className="font-medium">{a.label}</dt>
            <dd className="whitespace-pre-wrap">{answerText(a.value)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

/** Every lesson of a student with this tutor, with attendance and reports (FR-16-4). */
export function StudentHistoryPage({ studentId }: { studentId: string }) {
  const { t, i18n } = useTranslation();
  const history = useQuery({
    queryKey: ["tutor", "student", studentId, "lessons"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutor/students/{student_id}/lessons", {
          params: { path: { student_id: studentId } },
        }),
      ),
  });
  if (history.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  if (!history.data) return <Alert tone="danger">{t("errors.generic")}</Alert>;
  const data = history.data;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{data.student.name}</h1>
      {data.attendance_percent !== null && data.attendance_percent !== undefined ? (
        <p className="text-sm">
          {t("studentHistory.attendance", { percent: data.attendance_percent })}
        </p>
      ) : null}
      {!data.lessons.length ? (
        <p className="text-sm text-muted-foreground">{t("studentHistory.none")}</p>
      ) : (
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{t("studentHistory.caption")}</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="py-1">
                {t("studentHistory.when")}
              </th>
              <th scope="col">{t("studentHistory.lesson")}</th>
              <th scope="col">{t("studentHistory.attendanceCol")}</th>
              <th scope="col">{t("studentHistory.report")}</th>
            </tr>
          </thead>
          <tbody>
            {data.lessons.map((row) => (
              <tr key={row.id} className="border-b border-border">
                <td className="py-1">
                  <Link to="/tutor/lessons/$lessonId" params={{ lessonId: row.id }}>
                    {formatDateTime(row.start, i18n.language)}
                  </Link>
                </td>
                <td>{row.title}</td>
                <td>
                  {row.outcome
                    ? t(`tutor.outcome.${row.outcome}`, { defaultValue: row.outcome })
                    : t(`portal.status.${row.status}`, { defaultValue: row.status })}
                </td>
                <td>
                  {row.report_id ? (
                    <Link to="/tutor/reports/$reportId" params={{ reportId: row.report_id }}>
                      {t(`studentHistory.reportStatus.${row.report_status}`, {
                        defaultValue: row.report_status,
                      })}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
