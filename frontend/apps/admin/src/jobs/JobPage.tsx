import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, ErrorFallback, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { formatRate } from "../catalogue/format";
import { RecordActivity } from "../crm/Activity";
import { NEXT_STATUSES, type JobStatus } from "./statuses";

type Job = components["schemas"]["Job"];
type JobTutor = components["schemas"]["JobTutor"];

const linkClass = "font-medium underline-offset-2 hover:underline";

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-border p-4">
      <h2 className="mb-3 font-semibold">{title}</h2>
      {children}
    </section>
  );
}

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
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (status) change.mutate();
      }}
    >
      <SelectField
        label={t("jobs.changeStatus")}
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
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      ) : null}
      {status === "paused" ? (
        <label className="flex h-10 items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={cancelFuture}
            onChange={(e) => setCancelFuture(e.target.checked)}
          />
          {t("jobs.cancelFuture")}
        </label>
      ) : null}
      <Button type="submit" variant="secondary" disabled={!status || change.isPending}>
        {t("jobs.apply")}
      </Button>
      <ErrorText error={change.error} />
    </form>
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
      className="mt-4 flex flex-wrap items-end gap-2"
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
    <div className="mt-3 rounded-md border border-border p-3">
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
          <ul className="list-disc pl-5">
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
    <Card title={t("jobs.tutors")}>
      {current.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("jobs.noTutor")}</p>
      ) : null}
      <ul className="space-y-3">
        {current.map((link) => (
          <li key={link.id}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <Link className={linkClass} to="/tutors/$tutorId" params={{ tutorId: link.tutor }}>
                  {link.tutor_name}
                </Link>
                <p className="text-sm text-muted-foreground">
                  {[
                    t(`jobs.role.${link.role ?? "lead"}`),
                    t(`jobs.tutorStatus.${link.status}`),
                    link.pay_rate_override ? formatRate(link.pay_rate_override, i18n.language) : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              {canManage && open ? (
                <div className="flex gap-2">
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
                </div>
              ) : null}
            </div>
            {replacing === link.id ? (
              <ReplaceTutor job={job} link={link} onDone={() => setReplacing(null)} />
            ) : null}
          </li>
        ))}
      </ul>
      {past.length ? (
        <p className="mt-3 text-sm text-muted-foreground">
          {t("jobs.previously")}: {past.map((x) => x.tutor_name).join(", ")}
        </p>
      ) : null}
      {canManage && open ? <AddTutor job={job} /> : null}
      <ErrorText error={remove.error} />
    </Card>
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
    <Card title={t("jobs.economics")}>
      {per ? (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="text-muted-foreground">{t("jobs.chargePerLesson")}</dt>
          <dd>{formatRate(per.charge, i18n.language)}</dd>
          {per.pay ? (
            <>
              <dt className="text-muted-foreground">{t("jobs.payPerLesson")}</dt>
              <dd>{formatRate(per.pay, i18n.language)}</dd>
              <dt className="text-muted-foreground">{t("jobs.margin")}</dt>
              <dd>
                {formatRate(per.margin, i18n.language)}
                {per.margin_percent ? ` (${per.margin_percent}%)` : ""}
              </dd>
            </>
          ) : null}
        </dl>
      ) : null}
      <p className="mt-2 text-xs text-muted-foreground">{summary.data.trace.join(" · ")}</p>
      <p className="mt-2 text-sm">
        {t("jobs.delivered", {
          completed: summary.data.lessons_completed,
          planned: summary.data.lessons_planned,
        })}
      </p>
    </Card>
  );
}

/** One job: details, students, tutors, status, economics and activity (E07-T07). */
export function JobPage({ jobId }: { jobId: string }) {
  const { t, i18n } = useTranslation();
  const canSeeCharge = usePermission("billing.rates.view_charge");
  const canChangeStatus = usePermission("jobs.job.change_status");
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
      <p className="mb-2 text-sm">
        <Link to="/jobs" className={linkClass}>
          {t("jobs.title")}
        </Link>
        {" · "}
        <Link to="/clients/$clientId" params={{ clientId: j.client }} className={linkClass}>
          {j.client_name}
        </Link>
      </p>
      <h1 className="text-2xl font-semibold">{j.name}</h1>
      <p className="mb-4 text-sm text-muted-foreground">
        {j.reference} · {t(`jobs.status.${j.status}`)} · {j.service_name}
      </p>
      {canChangeStatus ? (
        <div className="mb-6">
          <StatusControl job={j} />
        </div>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={t("jobs.details")}>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
            {canSeeCharge && j.charge_rate ? (
              <>
                <dt className="text-muted-foreground">{t("jobs.chargeRate")}</dt>
                <dd>{formatRate(j.charge_rate, i18n.language)}</dd>
              </>
            ) : null}
            <dt className="text-muted-foreground">{t("jobs.billing")}</dt>
            <dd>{t(`jobs.billingMethod.${j.billing_method ?? "pay_as_you_go"}`)}</dd>
            {j.start_date ? (
              <>
                <dt className="text-muted-foreground">{t("jobs.starts")}</dt>
                <dd>{formatDate(j.start_date, i18n.language)}</dd>
              </>
            ) : null}
            {j.default_schedule?.length ? (
              <>
                <dt className="text-muted-foreground">{t("jobs.schedule")}</dt>
                <dd>
                  {j.default_schedule
                    .map((slot) => `${t(`jobs.weekday.${slot.weekday}`)} ${slot.time}`)
                    .join(", ")}
                </dd>
              </>
            ) : null}
            {j.hours_cap ? (
              <>
                <dt className="text-muted-foreground">{t("jobs.hoursCap")}</dt>
                <dd>
                  {t(`jobs.cap.${j.hours_cap_period ?? "total"}`, { hours: Number(j.hours_cap) })}
                </dd>
              </>
            ) : null}
          </dl>
          {j.notes_for_tutor ? <p className="mt-3 text-sm">{j.notes_for_tutor}</p> : null}
        </Card>
        <Card title={t("jobs.students")}>
          <ul className="space-y-2">
            {j.students.map((link) => (
              <li key={link.id} className={link.active_to ? "text-muted-foreground" : undefined}>
                <Link
                  className={linkClass}
                  to="/students/$studentId"
                  params={{ studentId: link.student }}
                >
                  {link.student_name}
                </Link>
                {link.charge_rate_override
                  ? ` · ${formatRate(link.charge_rate_override, i18n.language)}`
                  : ""}
                {link.active_to
                  ? ` · ${t("jobs.leftOn", { when: formatDate(link.active_to, i18n.language) })}`
                  : ""}
              </li>
            ))}
          </ul>
        </Card>
        <Tutors job={j} />
        {canSeeCharge ? <Summary jobId={j.id} /> : null}
      </div>
      <RecordActivity target={{ target_type: "jobs.job", target_id: j.id }} />
    </article>
  );
}
