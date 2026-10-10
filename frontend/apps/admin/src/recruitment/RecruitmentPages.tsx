import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";

import { api, usePermission } from "../api";
import { Turnstile } from "../components/Turnstile";
import { PublicLayout } from "../layout/PublicLayout";
import { PublicField, type Schema } from "../leads/MorePages";

function Page({ title, children }: { title: string; children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <nav aria-label={t("recruitment.title")} className="flex gap-3 text-sm">
        <Link to="/recruitment" activeOptions={{ exact: true }} className="[&.active]:font-medium">
          {t("recruitment.applications")}
        </Link>
        <Link to="/compliance" className="[&.active]:font-medium">
          {t("recruitment.compliance")}
        </Link>
      </nav>
      {children}
    </div>
  );
}

/** Applications by stage (FR-18-2). */
export function ApplicationsPage() {
  const { t } = useTranslation();
  const stages = useQuery({
    queryKey: ["application-stages"],
    queryFn: async () => unwrap(await api.GET("/api/v1/application-stages")),
  });
  const applications = useQuery({
    queryKey: ["applications", "open"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/applications", {
          params: { query: { status: "open", page_size: 200 } },
        }),
      ),
  });
  return (
    <Page title={t("recruitment.title")}>
      {applications.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      <div className="flex gap-3 overflow-x-auto pb-2">
        {stages.data
          ?.filter((s) => s.kind === "open")
          .map((stage) => {
            const cards = applications.data?.results.filter((a) => a.stage === stage.id) ?? [];
            return (
              <section
                key={stage.id}
                aria-label={stage.name}
                className="w-64 shrink-0 rounded-md bg-muted/50 p-2"
              >
                <h2 className="mb-2 flex justify-between text-sm font-semibold">
                  <span>{stage.name}</span>
                  <span className="text-muted-foreground">{cards.length}</span>
                </h2>
                <ul className="space-y-2">
                  {cards.map((a) => (
                    <li
                      key={a.id}
                      className="rounded-md border border-border bg-background p-2 text-sm"
                    >
                      <Link
                        to="/recruitment/$id"
                        params={{ id: a.id }}
                        className="font-medium underline"
                      >
                        {a.full_name}
                      </Link>
                      <p className="text-xs text-muted-foreground">
                        {(a.subjects as { subject: string }[]).map((s) => s.subject).join(", ")}
                        {a.opening_title ? ` · ${a.opening_title}` : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
      </div>
    </Page>
  );
}

/** One application: scorecards, references, interview, decision. */
export function ApplicationPage({ id }: { id: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canDecide = usePermission("recruitment.application.decide");
  const [reason, setReason] = useState("");
  const [referee, setReferee] = useState({ name: "", email: "" });
  const [slot, setSlot] = useState("");
  const application = useQuery({
    queryKey: ["application", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/applications/{id}", { params: { path: { id } } })),
  });
  const stages = useQuery({
    queryKey: ["application-stages"],
    queryFn: async () => unwrap(await api.GET("/api/v1/application-stages")),
  });
  const path = { params: { path: { id } } };
  const set = (data: unknown) => queryClient.setQueryData(["application", id], data);
  const move = useMutation({
    mutationFn: async (stage: string) =>
      unwrap(await api.POST("/api/v1/applications/{id}/move", { ...path, body: { stage } })),
    onSuccess: set,
  });
  const approve = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/applications/{id}/approve", {
          ...path,
          body: { employment_type: "self_employed" },
        }),
      ),
    onSuccess: set,
  });
  const reject = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/applications/{id}/reject", {
          ...path,
          body: { reason, talent_pool: false, notify: true },
        }),
      ),
    onSuccess: set,
  });
  const reference = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/applications/{id}/references", {
          ...path,
          body: { ...referee, relationship: "" },
        }),
      ),
    onSuccess: set,
  });
  const interview = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/applications/{id}/interviews", {
          ...path,
          body: { options: [new Date(slot).toISOString()], minutes: 30, meeting_url: "" },
        }),
      ),
    onSuccess: set,
  });
  if (!application.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const a = application.data;
  const error = move.error ?? approve.error ?? reject.error ?? reference.error ?? interview.error;
  return (
    <Page title={a.full_name}>
      <p className="text-sm">
        {a.stage_name} · {t(`recruitment.status.${a.status}`)} · {a.email}
        {a.phone ? ` · ${a.phone}` : ""} · {formatDate(a.created_at)}
      </p>
      <section className="space-y-1 rounded-md border border-border p-4 text-sm">
        <p>
          {t("recruitment.subjects")}:{" "}
          {(a.subjects as { subject: string }[]).map((s) => s.subject).join(", ") || "–"}
        </p>
        {a.experience ? <p className="whitespace-pre-line">{a.experience}</p> : null}
        {Object.entries(a.answers as Record<string, unknown>).map(([q, v]) => (
          <p key={q}>
            <strong>{q}</strong>: {String(v)}
          </p>
        ))}
      </section>
      {a.status === "open" ? (
        <section className="space-y-3 rounded-md border border-border p-4">
          <label className="flex items-center gap-2 text-sm">
            <span>{t("recruitment.stage")}</span>
            <select
              className="h-9 rounded-md border border-border bg-background px-2"
              value={a.stage}
              onChange={(e) => move.mutate(e.target.value)}
            >
              {stages.data
                ?.filter((s) => s.kind === "open")
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
            </select>
          </label>
          <div className="flex flex-wrap items-end gap-2">
            <TextField
              label={t("recruitment.interviewTime")}
              type="datetime-local"
              value={slot}
              onChange={(e) => setSlot(e.target.value)}
            />
            <Button variant="secondary" disabled={!slot} onClick={() => interview.mutate()}>
              {t("recruitment.inviteToInterview")}
            </Button>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <TextField
              label={t("recruitment.refereeName", { n: "" })}
              value={referee.name}
              onChange={(e) => setReferee({ ...referee, name: e.target.value })}
            />
            <TextField
              label={t("recruitment.refereeEmail", { n: "" })}
              type="email"
              value={referee.email}
              onChange={(e) => setReferee({ ...referee, email: e.target.value })}
            />
            <Button
              variant="secondary"
              disabled={!referee.email}
              onClick={() => reference.mutate()}
            >
              {t("recruitment.requestReference")}
            </Button>
          </div>
          {canDecide ? (
            <div className="flex flex-wrap items-end gap-2">
              <Button onClick={() => approve.mutate()} loading={approve.isPending}>
                {t("recruitment.approve")}
              </Button>
              <TextField
                label={t("recruitment.rejectReason")}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
              <Button variant="ghost" disabled={!reason} onClick={() => reject.mutate()}>
                {t("recruitment.reject")}
              </Button>
            </div>
          ) : null}
          {error ? <Alert tone="danger">{error.message}</Alert> : null}
        </section>
      ) : null}
      <section className="space-y-1 text-sm">
        <h2 className="font-semibold">{t("recruitment.references")}</h2>
        {a.references.map((r) => (
          <p key={r.id}>
            {r.referee_name} · {t(`recruitment.referenceStatus.${r.status}`)}
            {r.rating ? ` · ${r.rating}/5` : ""}
            {r.concerns ? ` · ${t("recruitment.concerns")}` : ""}
          </p>
        ))}
        <h2 className="font-semibold">{t("recruitment.interviews")}</h2>
        {a.interviews.map((i) => (
          <p key={i.id}>{i.start ? formatDateTime(i.start) : t("recruitment.awaitingChoice")}</p>
        ))}
        <h2 className="font-semibold">{t("recruitment.scorecards")}</h2>
        {a.scorecards.map((sc) => (
          <p key={sc.id}>
            {sc.reviewer_name} · {sc.stage_name} ·{" "}
            {t(`recruitment.recommendations.${sc.recommendation}`)}
          </p>
        ))}
      </section>
    </Page>
  );
}

const CELL_TONE: Record<string, string> = {
  verified: "bg-green-100 text-green-900",
  submitted: "bg-amber-100 text-amber-900",
  missing: "bg-red-100 text-red-900",
  rejected: "bg-red-100 text-red-900",
  expired: "bg-red-100 text-red-900",
};

/** Tutors × requirements (FR-18-8). */
export function ComplianceDashboardPage() {
  const { t } = useTranslation();
  const board = useQuery({
    queryKey: ["compliance-dashboard"],
    queryFn: async () => unwrap(await api.GET("/api/v1/compliance/dashboard")),
  });
  if (!board.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  return (
    <Page title={t("recruitment.compliance")}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th scope="col">{t("recruitment.tutor")}</th>
              {board.data.requirements.map((r) => (
                <th key={r.key} scope="col">
                  {r.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {board.data.rows.map((row) => (
              <tr key={row.tutor} className="border-t border-border">
                <th scope="row" className="text-left font-normal">
                  <Link to="/tutors/$tutorId" params={{ tutorId: row.tutor }} className="underline">
                    {row.name}
                  </Link>
                  {row.status === "restricted" ? ` · ${t("recruitment.restricted")}` : ""}
                </th>
                {board.data.requirements.map((r) => {
                  const cell = row.cells[r.key];
                  return (
                    <td key={r.key}>
                      <span className={`rounded px-1 ${CELL_TONE[cell?.status ?? ""] ?? ""}`}>
                        {t(`recruitment.cell.${cell?.status ?? "missing"}`)}
                      </span>
                      {cell?.expiry_date ? (
                        <span className="block text-xs text-muted-foreground">
                          {formatDate(cell.expiry_date)}
                        </span>
                      ) : null}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}

/** Compliance records on the tutor record, with verify and reject (FR-18-6). */
export function TutorComplianceCard({ tutorId }: { tutorId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canView = usePermission("compliance.view");
  const canVerify = usePermission("compliance.verify");
  const data = useQuery({
    queryKey: ["tutor-compliance", tutorId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors/{id}/compliance", { params: { path: { id: tutorId } } }),
      ),
    enabled: canView,
  });
  const decide = useMutation({
    mutationFn: async ({ id, ok }: { id: string; ok: boolean }) =>
      ok
        ? unwrap(
            await api.POST("/api/v1/compliance/records/{id}/verify", { params: { path: { id } } }),
          )
        : unwrap(
            await api.POST("/api/v1/compliance/records/{id}/reject", {
              params: { path: { id } },
              body: { reason: t("recruitment.defaultRejectReason") },
            }),
          ),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["tutor-compliance", tutorId] }),
  });
  if (!canView || !data.data) return null;
  const records = new Map(data.data.records.map((r) => [r.requirement, r]));
  return (
    <section className="rounded-lg border border-border p-4 text-sm" aria-labelledby="compliance">
      <h2 id="compliance" className="mb-2 font-semibold">
        {t("recruitment.compliance")}
        {data.data.restricted ? ` · ${t("recruitment.restricted")}` : ""}
      </h2>
      <ul className="space-y-1">
        {data.data.requirements.map((req) => {
          const record = records.get(req.id);
          return (
            <li key={req.id} className="flex flex-wrap items-center justify-between gap-2">
              <span>
                {req.name}:{" "}
                {t(
                  `recruitment.cell.${record && !record.valid && record.status === "verified" ? "expired" : (record?.status ?? "missing")}`,
                )}
                {record?.expiry_date ? ` · ${formatDate(record.expiry_date)}` : ""}
              </span>
              {canVerify && record?.status === "submitted" ? (
                <span className="flex gap-1">
                  <Button size="sm" onClick={() => decide.mutate({ id: record.id, ok: true })}>
                    {t("recruitment.verify")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => decide.mutate({ id: record.id, ok: false })}
                  >
                    {t("recruitment.reject")}
                  </Button>
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
      {decide.error ? <Alert tone="danger">{decide.error.message}</Alert> : null}
    </section>
  );
}

// --- public pages ---------------------------------------------------------------------------

/** Open roles at ``/vacancies`` and the application form at ``/vacancies/<slug>`` (FR-18-1). */
export function VacanciesPage() {
  const { t } = useTranslation();
  const openings = useQuery({
    queryKey: ["public-openings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/public/job-openings")),
  });
  return (
    <PublicLayout title={t("recruitment.jobsTitle")}>
      {openings.data && !openings.data.length ? <p>{t("recruitment.noOpenings")}</p> : null}
      <ul className="space-y-3">
        {openings.data?.map((o) => (
          <li key={o.slug}>
            <a className="font-medium underline" href={`/vacancies/${o.slug}`}>
              {o.title}
            </a>
            {o.location ? <span className="text-muted-foreground"> · {o.location}</span> : null}
          </li>
        ))}
      </ul>
    </PublicLayout>
  );
}

export function VacancyPage({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [token, setToken] = useState("");
  const opening = useQuery({
    queryKey: ["public-opening", slug],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/public/job-openings/{slug}", { params: { path: { slug } } })),
    retry: false,
  });
  const apply = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/public/job-openings/{slug}", {
          params: { path: { slug } },
          body: { data: answers as Record<string, never>, captcha_token: token, website: "" },
        }),
      ),
  });
  if (opening.isError)
    return <PublicLayout title={t("recruitment.noOpening")}>{null}</PublicLayout>;
  if (!opening.data) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
  const schema = opening.data.schema as unknown as Schema;
  const errors = (apply.error as { problem?: { errors?: Record<string, string[]> } } | null)
    ?.problem?.errors;
  return (
    <PublicLayout title={opening.data.title}>
      {opening.data.description ? (
        <p className="mb-4 whitespace-pre-line">{opening.data.description}</p>
      ) : null}
      {apply.isSuccess ? (
        <p role="status">{t("recruitment.applied")}</p>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            apply.mutate();
          }}
        >
          {schema.steps.flatMap((step) =>
            step.fields.map((f) => (
              <PublicField
                key={f.key}
                field={f}
                value={answers[f.key]}
                error={errors?.[f.key]?.[0]}
                onChange={(v) => setAnswers({ ...answers, [f.key]: v })}
              />
            )),
          )}
          {opening.data.turnstile_site_key ? (
            <Turnstile siteKey={opening.data.turnstile_site_key} onToken={setToken} />
          ) : null}
          {apply.error && !errors ? <Alert tone="danger">{apply.error.message}</Alert> : null}
          <Button type="submit" loading={apply.isPending}>
            {t("recruitment.apply")}
          </Button>
        </form>
      )}
    </PublicLayout>
  );
}

/** The applicant picks an interview time at ``/interviews/<token>``. */
export function InterviewChoicePage({ token }: { token: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const interview = useQuery({
    queryKey: ["interview", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/public/interviews/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const book = useMutation({
    mutationFn: async (start: string) =>
      unwrap(
        await api.POST("/api/v1/public/interviews/{token}", {
          params: { path: { token } },
          body: { start },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["interview", token], data),
  });
  if (interview.isError)
    return <PublicLayout title={t("recruitment.linkExpired")}>{null}</PublicLayout>;
  if (!interview.data) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
  const i = interview.data;
  return (
    <PublicLayout title={t("recruitment.chooseTime", { organisation: i.organisation })}>
      {i.status === "booked" && i.start ? (
        <p role="status">{t("recruitment.interviewBooked", { when: formatDateTime(i.start) })}</p>
      ) : (
        <ul className="space-y-2">
          {i.options.map((option) => (
            <li key={option}>
              <Button variant="secondary" onClick={() => book.mutate(option)}>
                {formatDateTime(option)}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {book.error ? <Alert tone="danger">{book.error.message}</Alert> : null}
    </PublicLayout>
  );
}

/** A referee gives a reference at ``/references/<token>`` (FR-18-4). */
export function ReferencePage({ token }: { token: string }) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [rating, setRating] = useState("4");
  const [concerns, setConcerns] = useState(false);
  const reference = useQuery({
    queryKey: ["reference", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/public/references/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const give = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/public/references/{token}", {
          params: { path: { token } },
          body: { responses: answers, rating: Number(rating), concerns },
        }),
      ),
  });
  if (reference.isError)
    return <PublicLayout title={t("recruitment.linkExpired")}>{null}</PublicLayout>;
  if (!reference.data) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
  const r = reference.data;
  if (give.isSuccess || r.status !== "requested") {
    return (
      <PublicLayout title={t("recruitment.referenceFor", { name: r.applicant })}>
        <p role="status">{t("recruitment.referenceThanks")}</p>
      </PublicLayout>
    );
  }
  return (
    <PublicLayout title={t("recruitment.referenceFor", { name: r.applicant })}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          give.mutate();
        }}
      >
        {r.questions.map((q, i) => (
          <label key={q} className="flex flex-col gap-1 text-sm">
            <span className="font-medium">{q}</span>
            <textarea
              className="rounded-md border border-border p-2"
              rows={3}
              value={answers[`q${i + 1}`] ?? ""}
              onChange={(e) => setAnswers({ ...answers, [`q${i + 1}`]: e.target.value })}
            />
          </label>
        ))}
        <label className="flex items-center gap-2 text-sm">
          <span>{t("recruitment.overallRating")}</span>
          <select
            className="h-9 rounded-md border border-border bg-background px-2"
            value={rating}
            onChange={(e) => setRating(e.target.value)}
          >
            {["5", "4", "3", "2", "1"].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={concerns}
            onChange={(e) => setConcerns(e.target.checked)}
          />
          {t("recruitment.raiseConcern")}
        </label>
        {give.error ? <Alert tone="danger">{give.error.message}</Alert> : null}
        <Button type="submit" loading={give.isPending}>
          {t("recruitment.sendReference")}
        </Button>
      </form>
    </PublicLayout>
  );
}
