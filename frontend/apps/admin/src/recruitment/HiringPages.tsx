import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api, usePermission } from "../api";
import { AiContentHelper } from "../ai/AiParts";
import { RecruitmentPage } from "./RecruitmentPages";

type Opening = components["schemas"]["JobOpening"];
type Subject = { subject: string; level: string };

const subjectsText = (subjects: unknown) =>
  ((subjects as Subject[] | undefined) ?? [])
    .map((s) => [s.subject, s.level].filter(Boolean).join(" "))
    .join(", ");

interface Draft {
  id?: string;
  title: string;
  slug: string;
  description: string;
  subjects: string;
  location: string;
  branch: string;
  form: string;
  published: boolean;
  closes_on: string;
}

const EMPTY: Draft = {
  title: "",
  slug: "",
  description: "",
  subjects: "",
  location: "",
  branch: "",
  form: "",
  published: false,
  closes_on: "",
};

const toDraft = (o: Opening): Draft => ({
  id: o.id,
  title: o.title,
  slug: o.slug ?? "",
  description: o.description ?? "",
  subjects: subjectsText(o.subjects),
  location: o.location ?? "",
  branch: o.branch ?? "",
  form: o.form ?? "",
  published: Boolean(o.published),
  closes_on: o.closes_on ?? "",
});

/** Job openings and their editor (FR-18-1, gap batch G5a) at ``/recruitment/openings``. */
export function OpeningsPage() {
  const { t } = useTranslation();
  const canManage = usePermission("recruitment.pipeline.manage");
  const [draft, setDraft] = useState<Draft | null>(null);
  const openings = useQuery({
    queryKey: ["job-openings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/job-openings")),
  });
  return (
    <RecruitmentPage
      title={t("hiring.openings.title")}
      description={t("hiring.openings.description")}
      actions={
        canManage ? (
          <Button onClick={() => setDraft({ ...EMPTY })}>{t("hiring.openings.new")}</Button>
        ) : null
      }
    >
      {openings.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {openings.data && !openings.data.length ? (
        <p className="text-muted-foreground">{t("hiring.openings.none")}</p>
      ) : null}
      {openings.data?.length ? (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th scope="col" className="px-4 py-2">
                  {t("hiring.openings.role")}
                </th>
                <th scope="col" className="px-4 py-2">
                  {t("hiring.openings.location")}
                </th>
                <th scope="col" className="px-4 py-2">
                  {t("hiring.openings.status")}
                </th>
                <th scope="col" className="px-4 py-2 text-right">
                  {t("hiring.openings.applications")}
                </th>
                <th scope="col" className="px-4 py-2">
                  <span className="sr-only">{t("hiring.openings.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {openings.data.map((o) => (
                <tr key={o.id}>
                  <th scope="row" className="px-4 py-2 text-left font-medium">
                    {o.title}
                    <span className="block text-xs font-normal text-muted-foreground">
                      {subjectsText(o.subjects)}
                    </span>
                  </th>
                  <td className="px-4 py-2">{o.location || "–"}</td>
                  <td className="px-4 py-2">
                    {o.published ? t("hiring.openings.published") : t("hiring.openings.draft")}
                    {o.closes_on ? (
                      <span className="block text-xs text-muted-foreground">
                        {t("hiring.openings.closes", { date: formatDate(o.closes_on) })}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{o.applications_open}</td>
                  <td className="px-4 py-2 text-right">
                    <span className="inline-flex gap-2">
                      {o.published ? (
                        <a className="text-link underline" href={`/vacancies/${o.slug}`}>
                          {t("hiring.openings.view", { title: o.title })}
                        </a>
                      ) : null}
                      {canManage ? (
                        <Button size="sm" variant="ghost" onClick={() => setDraft(toDraft(o))}>
                          {t("hiring.openings.edit", { title: o.title })}
                        </Button>
                      ) : null}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {draft ? <OpeningEditor initial={draft} onClose={() => setDraft(null)} /> : null}
    </RecruitmentPage>
  );
}

function OpeningEditor({ initial, onClose }: { initial: Draft; onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [d, setD] = useState<Draft>(initial);
  const set = (patch: Partial<Draft>) => setD({ ...d, ...patch });
  const forms = useQuery({
    queryKey: ["forms"],
    queryFn: async () => unwrap(await api.GET("/api/v1/forms")),
  });
  const branches = useQuery({
    queryKey: ["branches"],
    queryFn: async () => unwrap(await api.GET("/api/v1/branches")).results,
  });
  const standard = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/job-openings/default-form")),
    onSuccess: (form) => {
      set({ form: form.id });
      void queryClient.invalidateQueries({ queryKey: ["forms"] });
    },
  });
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        title: d.title,
        slug: d.slug,
        description: d.description,
        subjects: d.subjects
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        location: d.location,
        branch: d.branch || null,
        form: d.form || null,
        published: d.published,
        closes_on: d.closes_on || null,
      };
      return d.id
        ? unwrap(
            await api.PATCH("/api/v1/job-openings/{id}", {
              params: { path: { id: d.id } },
              body: body as never,
            }),
          )
        : unwrap(await api.POST("/api/v1/job-openings", { body: body as never }));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["job-openings"] });
      onClose();
    },
  });
  const errors = (save.error as { problem?: { errors?: Record<string, string[]> } } | null)?.problem
    ?.errors;
  const applicationForms = (forms.data ?? []).filter((f) => f.type === "application");
  return (
    <section
      aria-labelledby="opening-editor"
      className="mt-6 space-y-4 rounded-xl border border-border bg-surface p-5"
    >
      <h2 id="opening-editor" className="text-base font-semibold">
        {d.id ? t("hiring.openings.editTitle") : t("hiring.openings.newTitle")}
      </h2>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label={t("hiring.openings.titleField")}
            required
            value={d.title}
            error={errors?.title?.[0]}
            onChange={(e) => set({ title: e.target.value })}
          />
          <TextField
            label={t("hiring.openings.slug")}
            hint={t("hiring.openings.slugHint")}
            value={d.slug}
            error={errors?.slug?.[0]}
            onChange={(e) => set({ slug: e.target.value })}
          />
          <TextField
            label={t("hiring.openings.subjects")}
            hint={t("hiring.openings.subjectsHint")}
            value={d.subjects}
            onChange={(e) => set({ subjects: e.target.value })}
          />
          <TextField
            label={t("hiring.openings.location")}
            value={d.location}
            onChange={(e) => set({ location: e.target.value })}
          />
          <SelectField
            label={t("hiring.openings.branch")}
            value={d.branch}
            onChange={(e) => set({ branch: e.target.value })}
            options={[
              { value: "", label: t("hiring.openings.allBranches") },
              ...(branches.data ?? []).map((b) => ({ value: b.id, label: b.name })),
            ]}
          />
          <TextField
            label={t("hiring.openings.closesOn")}
            type="date"
            value={d.closes_on}
            onChange={(e) => set({ closes_on: e.target.value })}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="opening-description" className="text-sm font-medium">
            {t("hiring.openings.descriptionField")}
          </label>
          <textarea
            id="opening-description"
            rows={6}
            className="rounded-md border border-field bg-surface p-3 text-sm"
            value={d.description}
            onChange={(e) => set({ description: e.target.value })}
          />
          <AiContentHelper
            kind="job_ad"
            title={d.title}
            onUse={(draft) => set({ title: d.title || draft.title, description: draft.body })}
          />
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <SelectField
            label={t("hiring.openings.form")}
            value={d.form}
            error={errors?.form?.[0]}
            onChange={(e) => set({ form: e.target.value })}
            options={[
              { value: "", label: t("hiring.openings.standardForm") },
              ...applicationForms.map((f) => ({ value: f.id, label: f.name })),
            ]}
          />
          <Button
            type="button"
            variant="secondary"
            loading={standard.isPending}
            onClick={() => standard.mutate()}
          >
            {t("hiring.openings.useStandard")}
          </Button>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={d.published}
            onChange={(e) => set({ published: e.target.checked })}
          />
          {t("hiring.openings.publish")}
        </label>
        {save.error && !errors ? <Alert tone="danger">{save.error.message}</Alert> : null}
        <div className="flex gap-2">
          <Button type="submit" loading={save.isPending}>
            {t("common.save")}
          </Button>
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
        </div>
      </form>
    </section>
  );
}

// --- tutor record: performance, probation and offboarding (FR-18-9) -------------------------

function Panel({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-border p-4 text-sm" aria-labelledby={id}>
      <h2 id={id} className="mb-3 font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** Probation reviews and performance notes on the tutor record. */
export function TutorPerformanceCard({ tutorId }: { tutorId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canView = usePermission("recruitment.performance.view");
  const canManage = usePermission("recruitment.performance.manage");
  const canSeeTests = usePermission("people.tutor.approve_subjects");
  const [due, setDue] = useState("");
  const [outcome, setOutcome] = useState("passed");
  const [notes, setNotes] = useState("");
  const [extendTo, setExtendTo] = useState("");
  const [kind, setKind] = useState("note");
  const [body, setBody] = useState("");
  const reviews = useQuery({
    queryKey: ["probation-reviews", tutorId],
    enabled: canView,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/probation-reviews", { params: { query: { tutor: tutorId } } }))
        .results,
  });
  const noteList = useQuery({
    queryKey: ["performance-notes", tutorId],
    enabled: canView,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/performance-notes", { params: { query: { tutor: tutorId } } }))
        .results,
  });
  const tests = useQuery({
    queryKey: ["tutor-subject-tests", tutorId],
    enabled: canSeeTests,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors/{id}/subject-tests", { params: { path: { id: tutorId } } }),
      ),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["probation-reviews", tutorId] });
    void queryClient.invalidateQueries({ queryKey: ["performance-notes", tutorId] });
  };
  const schedule = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/probation-reviews", { body: { tutor: tutorId, due_on: due } }),
      ),
    onSuccess: refresh,
  });
  const complete = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/probation-reviews/{id}/complete", {
          params: { path: { id } },
          body: {
            outcome: outcome as "passed" | "extended" | "failed" | "cancelled",
            notes,
            extend_to: outcome === "extended" ? extendTo || null : null,
          },
        }),
      ),
    onSuccess: () => {
      setNotes("");
      refresh();
    },
  });
  const addNote = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/performance-notes", {
          body: { tutor: tutorId, kind: kind as "praise" | "concern" | "note", body },
        }),
      ),
    onSuccess: () => {
      setBody("");
      refresh();
    },
  });
  if (!canView) return null;
  const open = reviews.data?.find((r) => r.status === "scheduled");
  const error = schedule.error ?? complete.error ?? addNote.error;
  return (
    <Panel id="tutor-performance" title={t("hiring.performance.title")}>
      <h3 className="font-medium">{t("hiring.performance.probation")}</h3>
      {open ? (
        <div className="mt-1 space-y-2">
          <p>{t("hiring.performance.dueOn", { date: formatDate(open.due_on) })}</p>
          {canManage ? (
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                complete.mutate(open.id);
              }}
            >
              <SelectField
                label={t("hiring.performance.outcome")}
                size="sm"
                value={outcome}
                onChange={(e) => setOutcome(e.target.value)}
                options={["passed", "extended", "failed", "cancelled"].map((o) => ({
                  value: o,
                  label: t(`hiring.performance.outcomes.${o}`),
                }))}
              />
              {outcome === "extended" ? (
                <TextField
                  label={t("hiring.performance.extendTo")}
                  type="date"
                  size="sm"
                  required
                  value={extendTo}
                  onChange={(e) => setExtendTo(e.target.value)}
                />
              ) : null}
              <TextField
                label={t("hiring.performance.notes")}
                size="sm"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
              <Button type="submit" size="sm" loading={complete.isPending}>
                {t("hiring.performance.record")}
              </Button>
            </form>
          ) : null}
        </div>
      ) : canManage ? (
        <form
          className="mt-1 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            schedule.mutate();
          }}
        >
          <TextField
            label={t("hiring.performance.reviewDate")}
            type="date"
            size="sm"
            required
            value={due}
            onChange={(e) => setDue(e.target.value)}
          />
          <Button type="submit" size="sm" variant="secondary" loading={schedule.isPending}>
            {t("hiring.performance.schedule")}
          </Button>
        </form>
      ) : (
        <p className="text-muted-foreground">{t("hiring.performance.noReview")}</p>
      )}
      {reviews.data?.filter((r) => r.status !== "scheduled").length ? (
        <ul className="mt-2 space-y-1">
          {reviews.data
            .filter((r) => r.status !== "scheduled")
            .map((r) => (
              <li key={r.id}>
                {formatDate(r.due_on)} · {t(`hiring.performance.outcomes.${r.status}`)}
                {r.outcome_notes ? ` · ${r.outcome_notes}` : ""}
                {r.reviewer_name ? (
                  <span className="text-muted-foreground"> · {r.reviewer_name}</span>
                ) : null}
              </li>
            ))}
        </ul>
      ) : null}
      <h3 className="mt-4 font-medium">{t("hiring.performance.notesTitle")}</h3>
      {canManage ? (
        <form
          className="mt-1 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            addNote.mutate();
          }}
        >
          <SelectField
            label={t("hiring.performance.kind")}
            size="sm"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            options={["note", "praise", "concern"].map((k) => ({
              value: k,
              label: t(`hiring.performance.kinds.${k}`),
            }))}
          />
          <TextField
            label={t("hiring.performance.note")}
            size="sm"
            required
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <Button type="submit" size="sm" variant="secondary" loading={addNote.isPending}>
            {t("hiring.performance.addNote")}
          </Button>
        </form>
      ) : null}
      <ul className="mt-2 space-y-1">
        {noteList.data?.map((n) => (
          <li key={n.id}>
            <span className="font-medium">{t(`hiring.performance.kinds.${n.kind ?? "note"}`)}</span>
            : {n.body}
            <span className="block text-xs text-muted-foreground">
              {n.author_name} · {formatDateTime(n.created_at)}
            </span>
          </li>
        ))}
      </ul>
      {tests.data?.length ? (
        <>
          <h3 className="mt-4 font-medium">{t("hiring.tests.results")}</h3>
          <ul className="mt-1 space-y-1">
            {tests.data.map((a) => (
              <li key={a.id}>
                {a.title} · {t("hiring.tests.score", { percent: Math.round(Number(a.percent)) })} ·{" "}
                {a.passed ? t("hiring.tests.passed") : t("hiring.tests.failed")} ·{" "}
                <span className="text-muted-foreground">{formatDate(a.submitted_at)}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
    </Panel>
  );
}

/** Offboarding a tutor: checklist, revoke access and finish (FR-18-9). */
export function TutorOffboardingCard({ tutorId }: { tutorId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("recruitment.offboarding.manage");
  const [reason, setReason] = useState("");
  const [leavingOn, setLeavingOn] = useState("");
  const path = { params: { path: { id: tutorId } } };
  const state = useQuery({
    queryKey: ["offboarding", tutorId],
    enabled: canManage,
    queryFn: async () => unwrap(await api.GET("/api/v1/tutors/{id}/offboarding", path)),
  });
  const set = (data: unknown) => {
    queryClient.setQueryData(["offboarding", tutorId], data);
    void queryClient.invalidateQueries({ queryKey: ["tutors", tutorId] });
  };
  const start = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/tutors/{id}/offboarding", {
          ...path,
          body: { reason, leaving_on: leavingOn || null },
        }),
      ),
    onSuccess: set,
  });
  const tick = useMutation({
    mutationFn: async (key: string) =>
      unwrap(
        await api.POST("/api/v1/tutors/{id}/offboarding/{key}/done", {
          params: { path: { id: tutorId, key } },
        }),
      ),
    onSuccess: set,
  });
  const revoke = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/tutors/{id}/offboarding/revoke-access", path)),
    onSuccess: set,
  });
  const finish = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/tutors/{id}/offboarding/complete", path)),
    onSuccess: set,
  });
  if (!canManage || !state.data) return null;
  const s = state.data;
  const running = s.id && !s.completed_at;
  const error = start.error ?? tick.error ?? revoke.error ?? finish.error;
  return (
    <Panel id="tutor-offboarding" title={t("hiring.offboarding.title")}>
      {s.completed_at ? (
        <p>{t("hiring.offboarding.finished", { date: formatDate(s.completed_at) })}</p>
      ) : null}
      {!running && !s.completed_at && s.tutor_status !== "archived" ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            start.mutate();
          }}
        >
          <TextField
            label={t("hiring.offboarding.reason")}
            size="sm"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <TextField
            label={t("hiring.offboarding.leavingOn")}
            type="date"
            size="sm"
            value={leavingOn}
            onChange={(e) => setLeavingOn(e.target.value)}
          />
          <Button type="submit" size="sm" variant="secondary" loading={start.isPending}>
            {t("hiring.offboarding.start")}
          </Button>
        </form>
      ) : null}
      {running ? (
        <>
          <p className="mb-2 text-muted-foreground">
            {s.reason ? `${s.reason} · ` : ""}
            {s.leaving_on
              ? t("hiring.offboarding.leaving", { date: formatDate(s.leaving_on) })
              : ""}
          </p>
          <ul className="space-y-2">
            {s.items.map((item) => (
              <li key={item.key} className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  <span aria-hidden="true">{item.done ? "✓ " : "○ "}</span>
                  {item.label}
                  <span className="sr-only">
                    {" "}
                    {item.done ? t("hiring.offboarding.done") : t("hiring.offboarding.todo")}
                  </span>
                  {item.auto && !item.done ? (
                    <span className="block text-xs text-muted-foreground">
                      {t("hiring.offboarding.auto")}
                    </span>
                  ) : null}
                </span>
                {!item.done && item.key === "access" ? (
                  <Button size="sm" variant="secondary" onClick={() => revoke.mutate()}>
                    {t("hiring.offboarding.revoke")}
                  </Button>
                ) : null}
                {!item.done && !item.auto ? (
                  <Button size="sm" variant="ghost" onClick={() => tick.mutate(item.key)}>
                    {t("hiring.offboarding.markDone", { item: item.label })}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
          <Button
            className="mt-3"
            size="sm"
            disabled={!s.items.every((i) => i.done)}
            loading={finish.isPending}
            onClick={() => finish.mutate()}
          >
            {t("hiring.offboarding.finish")}
          </Button>
        </>
      ) : null}
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
    </Panel>
  );
}
