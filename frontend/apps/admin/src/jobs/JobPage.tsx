import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  ErrorFallback,
  FactList,
  NamePlate,
  Panel,
  PanelRow,
  PanelRows,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { formatRate } from "../catalogue/format";
import {
  BackSeparator,
  HeaderReveal,
  RecordHeader,
  RecordLayout,
} from "../components/RecordHeader";
import { RecordActivity } from "../crm/Activity";
import { NEXT_STATUSES, type JobStatus } from "./statuses";

type Job = components["schemas"]["Job"];
type JobTutor = components["schemas"]["JobTutor"];

const linkClass = "font-medium underline-offset-2 hover:underline";

function ErrorText({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  const messages = Object.values(fieldErrors(error));
  return (
    <Alert tone="danger" className="mt-2">
      {messages.length ? messages.join(" ") : t("errors.generic")}
    </Alert>
  );
}

function useInvalidateJob(jobId: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
  };
}

function StatusControl({ job }: { job: Job }) {
  const { t } = useTranslation();
  const refresh = useInvalidateJob(job.id);
  const next = NEXT_STATUSES[job.status as JobStatus] ?? [];
  const [status, setStatus] = useState<JobStatus | "">("");
  const [reason, setReason] = useState("");
  const [cancelFuture, setCancelFuture] = useState(false);
  const change = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/jobs/{id}/status", {
          params: { path: { id: job.id } },
          body: {
            status: status as JobStatus,
            reason,
            future_lessons: cancelFuture ? "cancel" : "keep",
          },
        }),
      ),
    onSuccess: () => {
      setStatus("");
      setReason("");
      refresh();
    },
  });
  if (!next.length) return null;
  return (
    <>
      <HeaderReveal label={t("jobs.changeStatus")}>
        {(close) => (
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (status) change.mutate(undefined, { onSuccess: close });
            }}
          >
            <SelectField
              label={t("jobs.changeStatus")}
              hideLabel
              size="sm"
              value={status}
              onChange={(e) => setStatus(e.target.value as JobStatus)}
              options={[
                { value: "", label: t("jobs.chooseStatus") },
                ...next.map((s) => ({ value: s, label: t(`jobs.status.${s}`) })),
              ]}
            />
            {status ? (
              <TextField
                label={t("jobs.reason")}
                hideLabel
                size="sm"
                placeholder={t("jobs.reason")}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            ) : null}
            {status === "paused" ? (
              <label className="flex h-9 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={cancelFuture}
                  onChange={(e) => setCancelFuture(e.target.checked)}
                />
                {t("jobs.cancelFuture")}
              </label>
            ) : null}
            <Button type="submit" size="sm" disabled={!status} loading={change.isPending}>
              {t("jobs.apply")}
            </Button>
          </form>
        )}
      </HeaderReveal>
      {change.error ? (
        <div className="basis-full">
          <ErrorText error={change.error} />
        </div>
      ) : null}
    </>
  );
}

function AddTutor({ job }: { job: Job }) {
  const { t } = useTranslation();
  const refresh = useInvalidateJob(job.id);
  const [tutor, setTutor] = useState("");
  const [offer, setOffer] = useState(false);
  const tutors = useQuery({
    queryKey: ["tutors", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors", {
          params: { query: { status: ["active"], page_size: 200 } },
        }),
      ),
  });
  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/jobs/{id}/tutors", {
          params: { path: { id: job.id } },
          body: { tutor, offer, role: "lead" },
        }),
      ),
    onSuccess: () => {
      setTutor("");
      refresh();
    },
  });
  return (
    <form
      className="flex flex-wrap items-end gap-2 border-t border-rule px-5 py-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (tutor) add.mutate();
      }}
    >
      <SelectField
        label={t("jobs.addTutor")}
        value={tutor}
        onChange={(e) => setTutor(e.target.value)}
        options={[
          { value: "", label: t("jobs.chooseTutor") },
          ...(tutors.data?.results ?? []).map((p) => ({ value: p.id, label: p.full_name })),
        ]}
      />
      <label className="flex h-10 items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4"
          checked={offer}
          onChange={(e) => setOffer(e.target.checked)}
        />
        {t("jobs.offerFirst")}
      </label>
      <Button type="submit" variant="secondary" disabled={!tutor || add.isPending}>
        {t("jobs.assign")}
      </Button>
      <ErrorText error={add.error} />
    </form>
  );
}

type Replacement = components["schemas"]["Replacement"];

function ReplaceTutor({ job, link, onDone }: { job: Job; link: JobTutor; onDone: () => void }) {
  const { t, i18n } = useTranslation();
  const refresh = useInvalidateJob(job.id);
  const [tutor, setTutor] = useState("");
  const [date, setDate] = useState("");
  const [preview, setPreview] = useState<Replacement | null>(null);
  const tutors = useQuery({
    queryKey: ["tutors", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors", {
          params: { query: { status: ["active"], page_size: 200 } },
        }),
      ),
  });
  const run = useMutation({
    mutationFn: async (dryRun: boolean) =>
      unwrap(
        await api.POST("/api/v1/jobs/{id}/tutors/{link_id}/replace", {
          params: { path: { id: job.id, link_id: link.id } },
          body: { tutor, effective_date: date, dry_run: dryRun },
        }),
      ),
    onSuccess: (result, dryRun) => {
      if (dryRun) {
        setPreview(result);
      } else {
        refresh();
        onDone();
      }
    },
  });
  return (
    <div className="mt-3 rounded-md border border-border bg-background p-3">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (tutor && date) run.mutate(true);
        }}
      >
        <SelectField
          label={t("jobs.replaceWith", { name: link.tutor_name })}
          value={tutor}
          onChange={(e) => {
            setTutor(e.target.value);
            setPreview(null);
          }}
          options={[
            { value: "", label: t("jobs.chooseTutor") },
            ...(tutors.data?.results ?? [])
              .filter((p) => p.id !== link.tutor)
              .map((p) => ({ value: p.id, label: p.full_name })),
          ]}
        />
        <TextField
          label={t("jobs.from")}
          type="date"
          value={date}
          onChange={(e) => {
            setDate(e.target.value);
            setPreview(null);
          }}
        />
        <Button type="submit" variant="secondary" disabled={!tutor || !date || run.isPending}>
          {t("jobs.previewChange")}
        </Button>
      </form>
      {preview ? (
        <div className="mt-3 space-y-2 text-sm" aria-live="polite">
          <p>{t("jobs.lessonsMove", { count: preview.lessons.length })}</p>
          {preview.conflicts ? (
            <Alert tone="warning">{t("jobs.conflicts", { count: preview.conflicts })}</Alert>
          ) : null}
          <ul className="list-disc pl-5 tabular-nums">
            {preview.lessons.slice(0, 10).map((lesson) => (
              <li key={lesson.id}>
                {formatDateTime(lesson.starts_at, i18n.language)}
                {lesson.conflict ? ` (${lesson.conflict})` : ""}
              </li>
            ))}
          </ul>
          <Button onClick={() => run.mutate(false)} disabled={run.isPending}>
            {t("jobs.confirmReplace")}
          </Button>
        </div>
      ) : null}
      <ErrorText error={run.error} />
    </div>
  );
}

function Tutors({ job }: { job: Job }) {
  const { t, i18n } = useTranslation();
  const refresh = useInvalidateJob(job.id);
  const canManage = usePermission("jobs.job.manage_tutors");
  const [replacing, setReplacing] = useState<string | null>(null);
  const remove = useMutation({
    mutationFn: async (linkId: string) =>
      unwrap(
        await api.POST("/api/v1/jobs/{id}/tutors/{link_id}/remove", {
          params: { path: { id: job.id, link_id: linkId } },
          body: { reason: "" },
        }),
      ),
    onSuccess: refresh,
  });
  const current = job.tutors.filter((x) => x.status === "active" || x.status === "offered");
  const past = job.tutors.filter((x) => x.status === "ended" || x.status === "declined");
  const open = job.status !== "completed" && job.status !== "cancelled";
  return (
    <Panel title={t("jobs.tutors")} flush>
      {current.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">{t("jobs.noTutor")}</p>
      ) : null}
      <PanelRows>
        {current.map((link) => (
          <PanelRow key={link.id}>
            <NamePlate
              name={
                <Link className={linkClass} to="/tutors/$tutorId" params={{ tutorId: link.tutor }}>
                  {link.tutor_name}
                </Link>
              }
              context={[
                t(`jobs.role.${link.role ?? "lead"}`),
                t(`jobs.tutorStatus.${link.status}`),
                link.pay_rate_override ? formatRate(link.pay_rate_override, i18n.language) : "",
              ]
                .filter(Boolean)
                .join(" · ")}
              aside={
                canManage && open ? (
                  <>
                    {link.status === "active" ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        aria-expanded={replacing === link.id}
                        aria-label={t("jobs.replaceNamed", { name: link.tutor_name })}
                        onClick={() => setReplacing(replacing === link.id ? null : link.id)}
                      >
                        {t("jobs.replace")}
                      </Button>
                    ) : null}
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t("jobs.removeNamed", { name: link.tutor_name })}
                      onClick={() => remove.mutate(link.id)}
                    >
                      {t("jobs.remove")}
                    </Button>
                  </>
                ) : null
              }
            />
            {replacing === link.id ? (
              <ReplaceTutor job={job} link={link} onDone={() => setReplacing(null)} />
            ) : null}
          </PanelRow>
        ))}
      </PanelRows>
      {past.length ? (
        <p className="border-t border-rule px-5 py-2.5 text-sm text-muted-foreground">
          {t("jobs.previously")}: {past.map((x) => x.tutor_name).join(", ")}
        </p>
      ) : null}
      {canManage && open ? <AddTutor job={job} /> : null}
      {remove.error ? (
        <div className="px-5 pb-4">
          <ErrorText error={remove.error} />
        </div>
      ) : null}
    </Panel>
  );
}

function Summary({ jobId }: { jobId: string }) {
  const { t, i18n } = useTranslation();
  const summary = useQuery({
    queryKey: ["job", jobId, "summary"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/jobs/{id}/summary", { params: { path: { id: jobId } } })),
  });
  if (!summary.data) return null;
  const per = summary.data.per_lesson;
  return (
    <Panel title={t("jobs.economics")} flush>
      {per ? (
        <FactList
          className="tabular-nums"
          items={[
            [t("jobs.chargePerLesson"), formatRate(per.charge, i18n.language)],
            ...(per.pay
              ? ([
                  [t("jobs.payPerLesson"), formatRate(per.pay, i18n.language)],
                  [
                    t("jobs.margin"),
                    `${formatRate(per.margin, i18n.language)}${
                      per.margin_percent ? ` (${per.margin_percent}%)` : ""
                    }`,
                  ],
                ] as [string, string][])
              : []),
          ]}
        />
      ) : null}
      <div className="space-y-1 border-t border-rule px-5 py-2.5">
        <p className="text-sm">
          {t("jobs.delivered", {
            completed: summary.data.lessons_completed,
            planned: summary.data.lessons_planned,
          })}
        </p>
        <p className="text-xs text-muted-foreground">{summary.data.trace.join(" · ")}</p>
      </div>
    </Panel>
  );
}

/** One job: details, students, tutors, status, economics and activity (E07-T07). */
/** One student on the job as a name plate: name, then year group · status (from the
 * student's record), any rate override and when they left the job. */
function JobStudentRow({ link }: { link: Job["students"][number] }) {
  const { t, i18n } = useTranslation();
  const canView = usePermission("people.student.view");
  const student = useQuery({
    queryKey: ["students", link.student],
    enabled: canView,
    retry: false,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/students/{id}", { params: { path: { id: link.student } } })),
  });
  const s = student.data;
  return (
    <PanelRow className={link.active_to ? "text-muted-foreground" : undefined}>
      <NamePlate
        name={
          <Link
            className={linkClass}
            to="/students/$studentId"
            params={{ studentId: link.student }}
          >
            {link.student_name}
          </Link>
        }
        context={
          [
            s?.year_group ?? "",
            s ? t(`people.studentStatus.${s.status ?? "active"}`) : "",
            link.charge_rate_override ? formatRate(link.charge_rate_override, i18n.language) : "",
            link.active_to
              ? t("jobs.leftOn", { when: formatDate(link.active_to, i18n.language) })
              : "",
          ]
            .filter(Boolean)
            .join(" · ") || undefined
        }
      />
    </PanelRow>
  );
}

export function JobPage({ jobId }: { jobId: string }) {
  const { t, i18n } = useTranslation();
  const canSeeCharge = usePermission("billing.rates.view_charge");
  const canChangeStatus = usePermission("jobs.job.change_status");
  const canMatch = usePermission("matching.search");
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/jobs/{id}", { params: { path: { id: jobId } } })),
  });
  if (job.isError) {
    return (
      <ErrorFallback
        title={t("errors.generic")}
        retryLabel={t("errors.retry")}
        onRetry={() => void job.refetch()}
      />
    );
  }
  if (!job.data) return <Spinner label={t("grid.loading")} />;
  const j = job.data;
  return (
    <article>
      <RecordHeader
        back={
          <>
            <Link to="/jobs">{t("jobs.title")}</Link>
            <BackSeparator />
            <Link to="/clients/$clientId" params={{ clientId: j.client }}>
              {j.client_name}
            </Link>
          </>
        }
        title={j.name ?? ""}
        description={`${j.reference} · ${t(`jobs.status.${j.status}`)} · ${j.service_name}`}
        actions={
          <>
            {canChangeStatus ? <StatusControl job={j} /> : null}
            {canMatch && j.status !== "completed" && j.status !== "cancelled" ? (
              <Link
                to="/jobs/$jobId/match"
                params={{ jobId: j.id }}
                className={buttonClass({ variant: "secondary", size: "sm" })}
              >
                {t("matching.findTutor")}
              </Link>
            ) : null}
          </>
        }
      />
      <RecordLayout
        main={
          <>
            <Tutors job={j} />
            <Panel title={t("jobs.students")} flush>
              <PanelRows>
                {j.students.map((link) => (
                  <JobStudentRow key={link.id} link={link} />
                ))}
              </PanelRows>
            </Panel>
            <RecordActivity target={{ target_type: "jobs.job", target_id: j.id }} />
          </>
        }
        side={
          <>
            <Panel title={t("jobs.details")} flush>
              <FactList
                items={[
                  [
                    t("jobs.chargeRate"),
                    canSeeCharge && j.charge_rate ? formatRate(j.charge_rate, i18n.language) : "",
                  ],
                  [
                    t("jobs.billing"),
                    t(`jobs.billingMethod.${j.billing_method ?? "pay_as_you_go"}`),
                  ],
                  [t("jobs.starts"), j.start_date ? formatDate(j.start_date, i18n.language) : ""],
                  [
                    t("jobs.schedule"),
                    (j.default_schedule ?? [])
                      .map((slot) => `${t(`jobs.weekday.${slot.weekday}`)} ${slot.time}`)
                      .join(", "),
                  ],
                  [
                    t("jobs.hoursCap"),
                    j.hours_cap
                      ? t(`jobs.cap.${j.hours_cap_period ?? "total"}`, {
                          hours: Number(j.hours_cap),
                        })
                      : "",
                  ],
                ]}
              />
              {j.notes_for_tutor ? (
                <p className="border-t border-rule px-5 py-2.5 text-sm whitespace-pre-line">
                  {j.notes_for_tutor}
                </p>
              ) : null}
            </Panel>
            {canSeeCharge ? <Summary jobId={j.id} /> : null}
          </>
        }
      />
    </article>
  );
}
