import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  NamePlate,
  Panel,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledTable,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Circle, CircleCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, usePermission } from "../api";
import { useIsPhone } from "../billing/useIsPhone";
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
  const phone = useIsPhone();
  const openings = useQuery({
    queryKey: ["job-openings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/job-openings")),
  });
  return (
    <RecruitmentPage
      title={t("hiring.openings.title")}
      description={t("hiring.openings.description")}
      actions={
        canManage && !draft ? (
          <Button onClick={() => setDraft({ ...EMPTY })}>{t("hiring.openings.new")}</Button>
        ) : null
      }
    >
      {draft ? (
        <OpeningEditor key={draft.id ?? "new"} initial={draft} onClose={() => setDraft(null)} />
      ) : null}
      {openings.isPending ? (
        <Spinner label={t("grid.loading")} />
      ) : (
        <RuledTable
          caption={t("hiring.openings.title")}
          empty={openings.data?.length ? undefined : t("hiring.openings.none")}
          columns={[
            { label: t("hiring.openings.role") },
            ...(phone
              ? []
              : [{ label: t("hiring.openings.location") }, { label: t("hiring.openings.status") }]),
            { label: t("hiring.openings.applications"), align: "right" as const },
            { label: t("hiring.openings.actions"), srOnly: true },
          ]}
        >
          {openings.data?.map((o) => {
            const status = o.published ? (
              t("hiring.openings.published")
            ) : (
              <span className="text-muted-foreground">{t("hiring.openings.draft")}</span>
            );
            const closes = o.closes_on
              ? t("hiring.openings.closes", { date: formatDate(o.closes_on) })
              : "";
            return (
              <tr key={o.id}>
                <th scope="row">
                  {o.title}
                  <span className="block text-xs font-normal text-muted-foreground">
                    {phone
                      ? [
                          o.location,
                          o.published ? t("hiring.openings.published") : t("hiring.openings.draft"),
                          closes,
                        ]
                          .filter(Boolean)
                          .join(" · ")
                      : subjectsText(o.subjects)}
                  </span>
                </th>
                {phone ? null : (
                  <>
                    <td>{o.location || <span className="text-muted-foreground">–</span>}</td>
                    <td>
                      {status}
                      {closes ? (
                        <span className="block text-xs text-muted-foreground tabular-nums">
                          {closes}
                        </span>
                      ) : null}
                    </td>
                  </>
                )}
                <td className="text-right tabular-nums">{o.applications_open}</td>
                <td className="text-right">
                  <span className="inline-flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
                    {o.published ? (
                      <a
                        className="text-link underline-offset-2 hover:underline"
                        href={`/vacancies/${o.slug}`}
                        aria-label={t("hiring.openings.view", { title: o.title })}
                      >
                        {t("designS8.view")}
                      </a>
                    ) : null}
                    {canManage ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        aria-label={t("hiring.openings.edit", { title: o.title })}
                        onClick={() => setDraft(toDraft(o))}
                      >
                        {t("designS8.edit")}
                      </Button>
                    ) : null}
                  </span>
                </td>
              </tr>
            );
          })}
        </RuledTable>
      )}
    </RecruitmentPage>
  );
}

function OpeningEditor({ initial, onClose }: { initial: Draft; onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [d, setD] = useState<Draft>(initial);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => first.current?.focus(), []);
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
    <Panel flush title={d.id ? t("hiring.openings.editTitle") : t("hiring.openings.newTitle")}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="space-y-4 px-5 py-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              ref={first}
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
              className="rounded-md border border-field bg-surface px-3 py-2 text-sm"
              value={d.description}
              onChange={(e) => set({ description: e.target.value })}
            />
            <div className="mt-1">
              <AiContentHelper
                kind="job_ad"
                title={d.title}
                onUse={(draft) => set({ title: d.title || draft.title, description: draft.body })}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-56 flex-1 sm:max-w-sm">
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
            </div>
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
              className="size-4"
              checked={d.published}
              onChange={(e) => set({ published: e.target.checked })}
            />
            {t("hiring.openings.publish")}
          </label>
          {save.error && !errors ? <Alert tone="danger">{save.error.message}</Alert> : null}
        </div>
        <PanelFooter>
          <Button type="submit" size="sm" loading={save.isPending}>
            {t("common.save")}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
        </PanelFooter>
      </form>
    </Panel>
  );
}

// --- tutor record: performance, probation and offboarding (FR-18-9) -------------------------

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
  const past = reviews.data?.filter((r) => r.status !== "scheduled") ?? [];
  const error = schedule.error ?? complete.error ?? addNote.error;
  return (
    <>
      <Panel
        title={t("hiring.performance.probation")}
        aside={
          open ? (
            <span className="tabular-nums">
              {t("hiring.performance.dueOn", { date: formatDate(open.due_on) })}
            </span>
          ) : null
        }
        flush
      >
        {open && canManage ? (
          <form
            className="flex flex-wrap items-end gap-2 px-5 py-4"
            aria-label={t("hiring.performance.record")}
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
            <div className="min-w-48 flex-1">
              <TextField
                label={t("hiring.performance.notes")}
                size="sm"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>
            <Button type="submit" size="sm" className="h-9" loading={complete.isPending}>
              {t("hiring.performance.record")}
            </Button>
          </form>
        ) : null}
        {!open && canManage ? (
          <form
            className="flex flex-wrap items-end gap-2 px-5 py-4"
            aria-label={t("hiring.performance.schedule")}
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
            <Button
              type="submit"
              size="sm"
              variant="secondary"
              className="h-9"
              loading={schedule.isPending}
            >
              {t("hiring.performance.schedule")}
            </Button>
          </form>
        ) : null}
        {!open && !canManage && !past.length ? (
          <p className="px-5 py-4 text-sm text-muted-foreground">
            {t("hiring.performance.noReview")}
          </p>
        ) : null}
        {past.length ? (
          <PanelRows className={canManage ? "border-t border-rule" : undefined}>
            {past.map((r) => (
              <PanelRow key={r.id}>
                <NamePlate
                  name={t(`hiring.performance.outcomes.${r.status}`)}
                  context={[formatDate(r.due_on), r.reviewer_name].filter(Boolean).join(" · ")}
                />
                {r.outcome_notes ? <p className="mt-1">{r.outcome_notes}</p> : null}
              </PanelRow>
            ))}
          </PanelRows>
        ) : null}
      </Panel>
      <Panel title={t("hiring.performance.notesTitle")} flush>
        {canManage ? (
          <form
            className="flex flex-wrap items-end gap-2 px-5 py-4"
            aria-label={t("hiring.performance.addNote")}
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
            <div className="min-w-48 flex-1">
              <TextField
                label={t("hiring.performance.note")}
                size="sm"
                required
                value={body}
                onChange={(e) => setBody(e.target.value)}
              />
            </div>
            <Button
              type="submit"
              size="sm"
              variant="secondary"
              className="h-9"
              loading={addNote.isPending}
            >
              {t("hiring.performance.addNote")}
            </Button>
          </form>
        ) : null}
        {noteList.data?.length ? (
          <PanelRows className={canManage ? "border-t border-rule" : undefined}>
            {noteList.data.map((n) => (
              <PanelRow key={n.id}>
                <p>
                  <span className="font-medium">
                    {t(`hiring.performance.kinds.${n.kind ?? "note"}`)}
                  </span>
                  {": "}
                  {n.body}
                </p>
                <p className="text-xs text-muted-foreground tabular-nums">
                  {n.author_name} · {formatDateTime(n.created_at)}
                </p>
              </PanelRow>
            ))}
          </PanelRows>
        ) : !canManage ? (
          <p className="px-5 py-4 text-sm text-muted-foreground">
            {t("designS8.recruitment.noNotes")}
          </p>
        ) : null}
      </Panel>
      {tests.data?.length ? (
        <Panel title={t("hiring.tests.results")} flush>
          <PanelRows>
            {tests.data.map((a) => (
              <PanelRow key={a.id}>
                <NamePlate
                  name={a.title}
                  context={<span className="tabular-nums">{formatDate(a.submitted_at)}</span>}
                  aside={
                    <span className="tabular-nums">
                      {t("hiring.tests.score", { percent: Math.round(Number(a.percent)) })} ·{" "}
                      {a.passed ? t("hiring.tests.passed") : t("hiring.tests.failed")}
                    </span>
                  }
                />
              </PanelRow>
            ))}
          </PanelRows>
        </Panel>
      ) : null}
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
    </>
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
  const context = running
    ? [
        s.reason,
        s.leaving_on ? t("hiring.offboarding.leaving", { date: formatDate(s.leaving_on) }) : "",
      ]
        .filter(Boolean)
        .join(" · ")
    : "";
  return (
    <Panel
      title={t("hiring.offboarding.title")}
      description={context || undefined}
      flush
      footer={
        running ? (
          <Button
            size="sm"
            disabled={!s.items.every((i) => i.done)}
            loading={finish.isPending}
            onClick={() => finish.mutate()}
          >
            {t("hiring.offboarding.finish")}
          </Button>
        ) : undefined
      }
    >
      {s.completed_at ? (
        <p className="px-5 py-4 text-sm">
          {t("hiring.offboarding.finished", { date: formatDate(s.completed_at) })}
        </p>
      ) : null}
      {!running && !s.completed_at && s.tutor_status !== "archived" ? (
        <form
          className="flex flex-wrap items-end gap-2 px-5 py-4"
          aria-label={t("hiring.offboarding.start")}
          onSubmit={(e) => {
            e.preventDefault();
            start.mutate();
          }}
        >
          <div className="min-w-48 flex-1">
            <TextField
              label={t("hiring.offboarding.reason")}
              size="sm"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          <TextField
            label={t("hiring.offboarding.leavingOn")}
            type="date"
            size="sm"
            value={leavingOn}
            onChange={(e) => setLeavingOn(e.target.value)}
          />
          <Button
            type="submit"
            size="sm"
            variant="secondary"
            className="h-9"
            loading={start.isPending}
          >
            {t("hiring.offboarding.start")}
          </Button>
        </form>
      ) : null}
      {running ? (
        <PanelRows>
          {s.items.map((item) => (
            <PanelRow key={item.key} className="flex flex-wrap items-center gap-x-3 gap-y-2">
              {item.done ? (
                <CircleCheck
                  aria-hidden="true"
                  strokeWidth={1.75}
                  className="size-4 shrink-0 text-foreground"
                />
              ) : (
                <Circle
                  aria-hidden="true"
                  strokeWidth={1.75}
                  className="size-4 shrink-0 text-field"
                />
              )}
              <span className="min-w-0 flex-1">
                <span className={item.done ? "text-muted-foreground" : undefined}>
                  {item.label}
                </span>
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
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label={t("hiring.offboarding.markDone", { item: item.label })}
                  onClick={() => tick.mutate(item.key)}
                >
                  {t("designS8.recruitment.markDone")}
                </Button>
              ) : null}
            </PanelRow>
          ))}
        </PanelRows>
      ) : null}
      {error ? (
        <div className="px-5 pb-4">
          <Alert tone="danger">{error.message}</Alert>
        </div>
      ) : null}
    </Panel>
  );
}
