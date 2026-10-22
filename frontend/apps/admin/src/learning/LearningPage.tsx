import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  figureCell,
  NamePlate,
  PageHeader,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  Tabs,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, useOrganisation, usePermission } from "../api";
import { markAssisted } from "../ai/ai";
import { AiAssistedBadge, AiFeedback } from "../ai/AiParts";
import { AiExplainToParent } from "../ai/AiWidgets";
import { KeyedSettings } from "../g3/KeyedSettings";
import { PAGE, localToIso, uploadFile, useStudentOptions } from "./hooks";
import { PanelLoading } from "../billing/moneyUi";
import { useIsPhone } from "../billing/useIsPhone";
import { Empty, fileInput, FormCard, Table, TextArea } from "./shared";

type Resource = components["schemas"]["Resource"];
type Assignment = components["schemas"]["Assignment"];
type ProgressReport = components["schemas"]["ProgressReport"];
type Loan = components["schemas"]["Loan"];
type QuestionKind = components["schemas"]["QuizQuestionKindEnum"];

const TABS = [
  "homework",
  "resources",
  "curricula",
  "assessments",
  "progress",
  "library",
  "quizzes",
] as const;
type Tab = (typeof TABS)[number];

function useInvalidate() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ["learning"] });
}

/** Learning tools (E21): homework, resources, curricula, assessments, progress reports,
 * the lending library and quizzes. */
export function LearningPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("homework");
  const [student, setStudent] = useState("");
  const options = useStudentOptions();
  return (
    <section>
      <PageHeader
        title={t("learning.title")}
        actions={
          <>
            <SelectField
              label={t("learning.studentProgress")}
              hideLabel
              size="sm"
              className="h-8 w-56"
              value={student}
              onChange={(e) => setStudent(e.target.value)}
              options={options}
            />
            {student ? (
              <Link
                to="/learning/students/$studentId"
                params={{ studentId: student }}
                className={buttonClass({ variant: "secondary", size: "sm" })}
              >
                {t("learning.openStudent")}
              </Link>
            ) : null}
          </>
        }
      />
      <Tabs
        label={t("learning.title")}
        tabs={TABS.map((key) => ({ key, label: t(`learning.tabs.${key}`) }))}
        value={tab}
        onChange={setTab}
      >
        {tab === "homework" ? <HomeworkSection /> : null}
        {tab === "resources" ? <ResourcesSection /> : null}
        {tab === "curricula" ? <CurriculaSection /> : null}
        {tab === "assessments" ? <AssessmentsSection /> : null}
        {tab === "progress" ? <ProgressSection /> : null}
        {tab === "library" ? <LibrarySection /> : null}
        {tab === "quizzes" ? <QuizzesSection /> : null}
      </Tabs>
    </section>
  );
}

// --- homework -----------------------------------------------------------------------------------

function HomeworkSection() {
  const { t, i18n } = useTranslation();
  const isPhone = useIsPhone();
  const canSet = usePermission("learning.homework.manage");
  const homework = useQuery({
    queryKey: ["learning", "homework"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/homework", {
          params: { query: { ...PAGE, status: "active" } },
        }),
      ),
  });
  const toReview = useQuery({
    queryKey: ["learning", "assignments", "submitted"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/homework-assignments", {
          params: { query: { ...PAGE, status: ["submitted"] } },
        }),
      ),
  });
  const waiting = toReview.data?.results ?? [];
  const set = homework.data?.results ?? [];
  return (
    <div className="space-y-6">
      <RuledPanel
        flush
        title={t("learning.homework.toReview")}
        rule={waiting.length ? "margin" : "border"}
        aside={
          waiting.length ? (
            <span className="font-semibold text-margin tabular-nums">{waiting.length}</span>
          ) : null
        }
      >
        {toReview.isPending ? (
          <PanelLoading label={t("grid.loading")} />
        ) : !waiting.length ? (
          <Empty>{t("learning.homework.nothingToReview")}</Empty>
        ) : (
          <PanelRows>
            {waiting.map((a) => (
              <PanelRow key={a.id} className="py-4">
                <ReviewCard assignment={a} />
              </PanelRow>
            ))}
          </PanelRows>
        )}
      </RuledPanel>
      <Table
        caption={t("learning.homework.set")}
        loading={homework.isPending}
        empty={homework.data && !set.length ? t("learning.homework.none") : undefined}
        columns={[
          { header: t("learning.homework.titleLabel") },
          ...(isPhone ? [] : [{ header: t("learning.homework.due") }]),
          { header: t("learning.homework.progress") },
          ...(isPhone ? [] : [{ header: t("learning.homework.setBy") }]),
        ]}
      >
        {set.map((h) => (
          <tr key={h.id}>
            <td className="font-medium">
              {h.title}
              {isPhone ? (
                <span className="block text-xs font-normal text-muted-foreground tabular-nums">
                  {formatDateTime(h.due_at, i18n.language)} · {h.set_by_name}
                </span>
              ) : null}
            </td>
            {isPhone ? null : (
              <td className="tabular-nums whitespace-nowrap">
                {formatDateTime(h.due_at, i18n.language)}
              </td>
            )}
            <td className="tabular-nums">
              {t("learning.homework.counts", {
                submitted: h.counts.submitted,
                completed: h.counts.completed,
                total: h.counts.total,
                overdue: h.counts.overdue,
              })}
            </td>
            {isPhone ? null : <td>{h.set_by_name}</td>}
          </tr>
        ))}
      </Table>
      {canSet ? <SetHomeworkForm /> : null}
    </div>
  );
}

export function ReviewCard({ assignment }: { assignment: Assignment }) {
  const { t, i18n } = useTranslation();
  const invalidate = useInvalidate();
  const [grade, setGrade] = useState("");
  const [feedback, setFeedback] = useState("");
  const review = useMutation({
    mutationFn: async (outcome: "complete" | "resubmit") =>
      unwrap(
        await api.POST("/api/v1/learning/homework-assignments/{id}/review", {
          params: { path: { id: assignment.id } },
          body: { outcome, grade, feedback },
        }),
      ),
    onSuccess: invalidate,
  });
  const latest = assignment.submissions[assignment.submissions.length - 1];
  return (
    <article
      aria-label={`${assignment.homework_title} – ${assignment.student_name}`}
      className="space-y-3"
    >
      <NamePlate
        name={`${assignment.homework_title} · ${assignment.student_name}`}
        context={
          latest ? (
            <span className="tabular-nums">
              {t("learning.homework.handedIn", {
                when: formatDateTime(latest.created_at, i18n.language),
              })}
              {latest.is_late ? ` · ${t("learning.homework.late")}` : ""}
            </span>
          ) : null
        }
      />
      {latest ? (
        <div className="space-y-1 text-sm">
          {latest.body ? <p className="whitespace-pre-wrap">{latest.body}</p> : null}
          {latest.link ? (
            <a
              className="break-all text-link underline-offset-2 hover:underline"
              href={latest.link}
              rel="noreferrer noopener"
              target="_blank"
            >
              {latest.link}
            </a>
          ) : null}
          {latest.files.map((f) => (
            <p key={f.id}>{f.filename}</p>
          ))}
        </div>
      ) : null}
      <div className="grid max-w-2xl gap-x-4 gap-y-3 sm:grid-cols-3">
        <TextField
          label={t("learning.homework.grade")}
          value={grade}
          onChange={(e) => setGrade(e.target.value)}
        />
        <TextArea
          label={t("learning.homework.feedback")}
          value={feedback}
          onChange={setFeedback}
          rows={2}
        />
      </div>
      {review.error ? <Alert tone="danger">{review.error.message}</Alert> : null}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={review.isPending}
          onClick={() => review.mutate("resubmit")}
        >
          {t("learning.homework.returnIt")}
        </Button>
        <Button
          type="button"
          size="sm"
          loading={review.isPending && review.variables === "complete"}
          disabled={review.isPending}
          onClick={() => review.mutate("complete")}
        >
          {t("learning.homework.markComplete")}
        </Button>
      </div>
    </article>
  );
}

export function SetHomeworkForm({
  studentOptions,
}: {
  studentOptions?: { value: string; label: string }[];
}) {
  const { t } = useTranslation();
  const invalidate = useInvalidate();
  const allStudents = useStudentOptions();
  const options = studentOptions ?? allStudents;
  const quizzes = useQuery({
    queryKey: ["learning", "quizzes"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/learning/quizzes", { params: { query: PAGE } })),
  });
  const [form, setForm] = useState({
    title: "",
    instructions: "",
    due: "",
    student: "",
    submission_type: "text" as components["schemas"]["HomeworkSubmissionTypeEnum"],
    quiz: "",
    minutes: "",
  });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/homework", {
          body: {
            title: form.title,
            instructions: form.instructions,
            due_at: localToIso(form.due),
            students: [form.student],
            submission_type: form.submission_type,
            quiz: form.submission_type === "quiz" ? form.quiz : null,
            expected_minutes: form.minutes ? Number(form.minutes) : null,
          },
        }),
      ),
    onSuccess: () => {
      setForm((f) => ({ ...f, title: "", instructions: "" }));
      void invalidate();
    },
  });
  const set = (key: keyof typeof form) => (value: string) =>
    setForm((f) => ({ ...f, [key]: value }));
  return (
    <FormCard
      title={t("learning.homework.new")}
      submit={t("learning.homework.setIt")}
      pending={create.isPending}
      error={create.error}
      onSubmit={() => create.mutate()}
      columns={3}
    >
      <TextField
        label={t("learning.homework.titleLabel")}
        required
        value={form.title}
        onChange={(e) => set("title")(e.target.value)}
      />
      <SelectField
        label={t("learning.student")}
        required
        value={form.student}
        onChange={(e) => set("student")(e.target.value)}
        options={options}
      />
      <TextField
        label={t("learning.homework.due")}
        type="datetime-local"
        required
        value={form.due}
        onChange={(e) => set("due")(e.target.value)}
      />
      <SelectField
        label={t("learning.homework.submissionType")}
        value={form.submission_type}
        onChange={(e) => set("submission_type")(e.target.value)}
        options={(["text", "file", "link", "none", "quiz"] as const).map((v) => ({
          value: v,
          label: t(`learning.homework.types.${v}`),
        }))}
      />
      {form.submission_type === "quiz" ? (
        <SelectField
          label={t("learning.quizzes.quiz")}
          required
          value={form.quiz}
          onChange={(e) => set("quiz")(e.target.value)}
          options={[
            { value: "", label: t("learning.quizzes.choose") },
            ...(quizzes.data?.results ?? []).map((q) => ({ value: q.id, label: q.title })),
          ]}
        />
      ) : null}
      <TextField
        label={t("learning.homework.minutes")}
        type="number"
        className="tabular-nums"
        min={1}
        value={form.minutes}
        onChange={(e) => set("minutes")(e.target.value)}
      />
      <TextArea
        label={t("learning.homework.instructions")}
        value={form.instructions}
        onChange={set("instructions")}
      />
    </FormCard>
  );
}

// --- resources ----------------------------------------------------------------------------------

function ResourcesSection() {
  const { t } = useTranslation();
  const isPhone = useIsPhone();
  const canManage = usePermission("learning.resource.manage");
  const [q, setQ] = useState("");
  const resources = useQuery({
    queryKey: ["learning", "resources", q],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/resources", {
          params: { query: { ...PAGE, archived: false, ...(q ? { q } : {}) } },
        }),
      ),
  });
  const storage = useQuery({
    queryKey: ["learning", "storage"],
    queryFn: async () => unwrap(await api.GET("/api/v1/learning/storage")),
  });
  const rows = resources.data?.results ?? [];
  const used = storage.data ? (storage.data.used_bytes / 1024 ** 3).toFixed(2) : "";
  return (
    <div className="space-y-6">
      <div>
        <div
          role="search"
          aria-label={t("designS6.learning.findResources")}
          className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2"
        >
          <div className="min-w-56 flex-1 sm:max-w-sm">
            <TextField
              label={t("learning.search")}
              hideLabel
              size="sm"
              type="search"
              placeholder={t("learning.search")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          {storage.data ? (
            <p className="text-sm text-muted-foreground tabular-nums sm:ml-auto">
              {storage.data.limit_gb
                ? t("learning.resources.storage", { used, limit: storage.data.limit_gb })
                : t("learning.resources.storageUnlimited", { used })}
            </p>
          ) : null}
        </div>
        <Table
          caption={t("learning.tabs.resources")}
          loading={resources.isPending}
          empty={resources.data && !rows.length ? t("learning.resources.none") : undefined}
          columns={[
            { header: t("learning.resources.titleLabel") },
            ...(isPhone
              ? []
              : [
                  { header: t("learning.resources.type") },
                  { header: t("learning.resources.library") },
                  { header: t("learning.resources.shared"), end: true, width: "w-20" },
                ]),
            { header: t("learning.resources.share"), hidden: true },
          ]}
        >
          {rows.map((r) => (
            <ResourceRow key={r.id} resource={r} />
          ))}
        </Table>
      </div>
      {canManage ? <NewResourceForm /> : null}
    </div>
  );
}

function ResourceRow({ resource }: { resource: Resource }) {
  const { t } = useTranslation();
  const isPhone = useIsPhone();
  const invalidate = useInvalidate();
  const canShare = usePermission("learning.resource.share");
  const options = useStudentOptions();
  const [student, setStudent] = useState("");
  const share = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/resources/{id}/share", {
          params: { path: { id: resource.id } },
          body: { students: [student] },
        }),
      ),
    onSuccess: () => {
      setStudent("");
      void invalidate();
    },
  });
  const open = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/resources/{id}/open", {
          params: { path: { id: resource.id } },
        }),
      ),
    onSuccess: (body) => window.open(body.url, "_blank", "noopener"),
  });
  const media = t(`learning.resources.media.${resource.media_type}`);
  return (
    <tr>
      <td>
        <button
          type="button"
          className="text-left font-medium underline-offset-2 hover:underline"
          onClick={() => open.mutate()}
        >
          {resource.title}
        </button>
        {isPhone ? (
          <span className="block text-xs text-muted-foreground">
            {[media, ...(resource.tags ?? [])].join(" · ")}
          </span>
        ) : resource.tags?.length ? (
          <span className="block text-xs text-muted-foreground">{resource.tags.join(", ")}</span>
        ) : null}
      </td>
      {isPhone ? null : (
        <>
          <td>{media}</td>
          <td>{resource.owner_name || t("learning.resources.orgLibrary")}</td>
          <td className={figureCell}>{resource.share_count}</td>
        </>
      )}
      <td className="py-1.5">
        {canShare ? (
          <form
            className="flex items-center justify-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (student) share.mutate();
            }}
          >
            <SelectField
              label={t("learning.resources.shareWith", { title: resource.title })}
              hideLabel
              size="sm"
              className="h-8 w-44"
              value={student}
              onChange={(e) => setStudent(e.target.value)}
              options={options}
            />
            <Button
              type="submit"
              size="sm"
              variant="secondary"
              disabled={!student}
              loading={share.isPending}
            >
              {t("learning.resources.share")}
            </Button>
          </form>
        ) : null}
        {share.error ? (
          <Alert tone="danger" className="mt-2">
            {share.error.message}
          </Alert>
        ) : null}
      </td>
    </tr>
  );
}

function NewResourceForm() {
  const { t } = useTranslation();
  const invalidate = useInvalidate();
  const [form, setForm] = useState({
    title: "",
    kind: "link" as "link" | "file",
    url: "",
    tags: "",
    visibility: "tutors" as components["schemas"]["ResourceVisibilityEnum"],
  });
  const [file, setFile] = useState<File | null>(null);
  const create = useMutation({
    mutationFn: async () => {
      const fileId = form.kind === "file" && file ? await uploadFile(file) : null;
      return unwrap(
        await api.POST("/api/v1/learning/resources", {
          body: {
            title: form.title,
            kind: form.kind,
            url: form.kind === "link" ? form.url : "",
            file: fileId,
            visibility: form.visibility,
            tags: form.tags
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean),
          },
        }),
      );
    },
    onSuccess: () => {
      setForm((f) => ({ ...f, title: "", url: "", tags: "" }));
      setFile(null);
      void invalidate();
    },
  });
  return (
    <FormCard
      title={t("learning.resources.new")}
      submit={t("learning.add")}
      pending={create.isPending}
      error={create.error}
      onSubmit={() => create.mutate()}
      columns={3}
    >
      <TextField
        label={t("learning.resources.titleLabel")}
        required
        value={form.title}
        onChange={(e) => setForm({ ...form, title: e.target.value })}
      />
      <SelectField
        label={t("learning.resources.type")}
        value={form.kind}
        onChange={(e) => setForm({ ...form, kind: e.target.value as "link" | "file" })}
        options={[
          { value: "link", label: t("learning.resources.link") },
          { value: "file", label: t("learning.resources.file") },
        ]}
      />
      {form.kind === "link" ? (
        <TextField
          label={t("learning.resources.url")}
          type="url"
          required
          value={form.url}
          onChange={(e) => setForm({ ...form, url: e.target.value })}
        />
      ) : (
        <TextField
          label={t("learning.resources.file")}
          type="file"
          required
          className={`${fileInput} h-10 pt-[3px]`}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      )}
      <SelectField
        label={t("learning.resources.visibility")}
        value={form.visibility}
        onChange={(e) =>
          setForm({
            ...form,
            visibility: e.target.value as components["schemas"]["ResourceVisibilityEnum"],
          })
        }
        options={(["tutors", "staff", "private"] as const).map((v) => ({
          value: v,
          label: t(`learning.resources.visibilities.${v}`),
        }))}
      />
      <TextField
        label={t("learning.resources.tags")}
        hint={t("learning.commaHint")}
        value={form.tags}
        onChange={(e) => setForm({ ...form, tags: e.target.value })}
      />
    </FormCard>
  );
}

// --- curricula ----------------------------------------------------------------------------------

function CurriculaSection() {
  const { t } = useTranslation();
  const invalidate = useInvalidate();
  const canManage = usePermission("learning.curriculum.manage");
  const [selected, setSelected] = useState("");
  const curricula = useQuery({
    queryKey: ["learning", "curricula"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/learning/curricula", { params: { query: PAGE } })),
  });
  const builtins = useQuery({
    queryKey: ["learning", "builtins"],
    queryFn: async () => unwrap(await api.GET("/api/v1/learning/curricula/builtins")),
  });
  const install = useMutation({
    mutationFn: async (key: string) =>
      unwrap(await api.POST("/api/v1/learning/curricula/install", { body: { key } })),
    onSuccess: invalidate,
  });
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/learning/curricula", { body: { name } })),
    onSuccess: (c) => {
      setName("");
      setSelected(c.id);
      void invalidate();
    },
  });
  const list = curricula.data?.results ?? [];
  const chosen = list.find((c) => c.id === selected);
  return (
    <div className="space-y-6">
      <Table
        caption={t("learning.tabs.curricula")}
        loading={curricula.isPending}
        empty={curricula.data && !list.length ? t("learning.curricula.none") : undefined}
        columns={[
          { header: t("learning.curricula.name") },
          { header: t("learning.curricula.topics"), end: true, width: "w-24" },
          { header: t("learning.curricula.open"), hidden: true },
        ]}
      >
        {list.map((c) => (
          <tr key={c.id}>
            <td className="font-medium">{c.name}</td>
            <td className={figureCell}>{c.topic_count}</td>
            <td className="py-1.5 text-right">
              <Button
                type="button"
                size="sm"
                variant="secondary"
                aria-pressed={selected === c.id}
                className="aria-pressed:bg-muted"
                onClick={() => setSelected(selected === c.id ? "" : c.id)}
              >
                {t("learning.curricula.open")}
              </Button>
            </td>
          </tr>
        ))}
      </Table>
      {selected ? (
        <CurriculumTree id={selected} name={chosen?.name ?? ""} canManage={canManage} />
      ) : null}
      {canManage ? (
        <>
          <RuledPanel flush title={t("learning.curricula.builtins")}>
            {builtins.isPending ? (
              <PanelLoading label={t("grid.loading")} />
            ) : (
              <PanelRows>
                {(builtins.data ?? []).map((b) => (
                  <PanelRow key={b.key}>
                    <NamePlate
                      name={b.name}
                      context={
                        <span className="tabular-nums">
                          {t("learning.curricula.size", { units: b.units, topics: b.topics })}
                        </span>
                      }
                      aside={
                        b.installed ? (
                          <span className="text-sm text-muted-foreground">
                            {t("learning.curricula.installed")}
                          </span>
                        ) : (
                          <Button
                            type="button"
                            size="sm"
                            variant="secondary"
                            aria-label={t("learning.curricula.install", { name: b.name })}
                            loading={install.isPending && install.variables === b.key}
                            disabled={install.isPending}
                            onClick={() => install.mutate(b.key)}
                          >
                            {t("designS6.learning.install")}
                          </Button>
                        )
                      }
                    />
                  </PanelRow>
                ))}
              </PanelRows>
            )}
            {install.error ? (
              <div className="border-t border-rule px-5 py-4">
                <Alert tone="danger">{install.error.message}</Alert>
              </div>
            ) : null}
          </RuledPanel>
          <FormCard
            title={t("learning.curricula.new")}
            submit={t("learning.add")}
            pending={create.isPending}
            error={create.error}
            onSubmit={() => create.mutate()}
          >
            <TextField
              label={t("learning.curricula.name")}
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </FormCard>
        </>
      ) : null}
    </div>
  );
}

function CurriculumTree({
  id,
  name,
  canManage,
}: {
  id: string;
  name: string;
  canManage: boolean;
}) {
  const { t } = useTranslation();
  const invalidate = useInvalidate();
  const tree = useQuery({
    queryKey: ["learning", "tree", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/learning/curricula/{id}/tree", { params: { path: { id } } })),
  });
  const importCsv = useMutation({
    mutationFn: async (file: File) =>
      unwrap(
        await api.POST("/api/v1/learning/curricula/{id}/import", {
          params: { path: { id } },
          body: { content: await file.text() },
        }),
      ),
    onSuccess: invalidate,
  });
  return (
    <RuledPanel
      flush
      title={name}
      footer={
        canManage ? (
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium" htmlFor={`csv-${id}`}>
              {t("learning.curricula.importCsv")}
            </label>
            <input
              id={`csv-${id}`}
              type="file"
              accept=".csv,text/csv"
              aria-describedby={`csv-${id}-hint`}
              className={fileInput}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) importCsv.mutate(file);
              }}
            />
            <p id={`csv-${id}-hint`} className="text-xs text-muted-foreground">
              {t("learning.curricula.csvHint")}
            </p>
          </div>
        ) : null
      }
    >
      {tree.isPending ? <PanelLoading label={t("grid.loading")} /> : null}
      <div className="divide-y divide-rule">
        {tree.data?.map((unit) => (
          <section key={unit.id} aria-label={unit.name} className="px-5 py-3">
            <h3 className="text-sm font-semibold">
              {unit.code ? <span className="mr-2 tabular-nums">{unit.code}</span> : null}
              {unit.name}
            </h3>
            <ul className="mt-1.5 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
              {unit.topics.map((topic) => (
                <li key={topic.id} className="flex gap-2">
                  {topic.code ? (
                    <span className="w-12 shrink-0 text-muted-foreground tabular-nums">
                      {topic.code}
                    </span>
                  ) : null}
                  <span>{topic.name}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      {importCsv.data || importCsv.error ? (
        <div className="border-t border-rule px-5 py-4">
          {importCsv.data ? (
            <p role="status" className="text-sm">
              {t("learning.curricula.imported", importCsv.data)}
            </p>
          ) : null}
          {importCsv.error ? <Alert tone="danger">{importCsv.error.message}</Alert> : null}
        </div>
      ) : null}
    </RuledPanel>
  );
}

// --- assessments --------------------------------------------------------------------------------

function AssessmentsSection() {
  const { t, i18n } = useTranslation();
  const isPhone = useIsPhone();
  const invalidate = useInvalidate();
  const canManage = usePermission("learning.assessment.manage");
  const options = useStudentOptions();
  const assessments = useQuery({
    queryKey: ["learning", "assessments"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/learning/assessments", { params: { query: PAGE } })),
  });
  const [form, setForm] = useState({
    name: "",
    kind: "mock_exam" as components["schemas"]["AssessmentKindEnum"],
    held_on: "",
    max_score: "",
  });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/assessments", {
          body: {
            name: form.name,
            kind: form.kind,
            held_on: form.held_on,
            max_score: form.max_score || null,
          },
        }),
      ),
    onSuccess: () => {
      setForm((f) => ({ ...f, name: "" }));
      void invalidate();
    },
  });
  const [result, setResult] = useState({ assessment: "", student: "", score: "", grade: "" });
  const record = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/assessment-results", {
          body: {
            assessment: result.assessment,
            student: result.student,
            score: result.score || null,
            grade: result.grade,
          },
        }),
      ),
    onSuccess: () => {
      setResult((r) => ({ ...r, student: "", score: "", grade: "" }));
      void invalidate();
    },
  });
  const list = assessments.data?.results ?? [];
  return (
    <div className="space-y-6">
      <Table
        caption={t("learning.tabs.assessments")}
        loading={assessments.isPending}
        empty={assessments.data && !list.length ? t("learning.assessments.none") : undefined}
        columns={[
          { header: t("learning.assessments.name") },
          ...(isPhone
            ? []
            : [{ header: t("learning.assessments.kind") }, { header: t("learning.assessments.date") }]),
          { header: t("learning.assessments.results"), end: true, width: "w-24" },
        ]}
      >
        {list.map((a) => (
          <tr key={a.id}>
            <td className="font-medium">
              {a.name}
              {isPhone ? (
                <span className="block text-xs font-normal text-muted-foreground tabular-nums">
                  {t(`learning.assessments.kinds.${a.kind}`)} · {formatDate(a.held_on, i18n.language)}
                </span>
              ) : null}
            </td>
            {isPhone ? null : (
              <>
                <td>{t(`learning.assessments.kinds.${a.kind}`)}</td>
                <td className="tabular-nums whitespace-nowrap">
                  {formatDate(a.held_on, i18n.language)}
                </td>
              </>
            )}
            <td className={figureCell}>{a.results_count}</td>
          </tr>
        ))}
      </Table>
      {canManage ? (
        <div className="grid items-start gap-6 lg:grid-cols-2">
          <FormCard
            title={t("learning.assessments.new")}
            submit={t("learning.add")}
            pending={create.isPending}
            error={create.error}
            onSubmit={() => create.mutate()}
          >
            <TextField
              label={t("learning.assessments.name")}
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            <SelectField
              label={t("learning.assessments.kind")}
              value={form.kind}
              onChange={(e) =>
                setForm({
                  ...form,
                  kind: e.target.value as components["schemas"]["AssessmentKindEnum"],
                })
              }
              options={(["diagnostic", "mock_exam", "quiz", "school_report", "other"] as const).map(
                (v) => ({ value: v, label: t(`learning.assessments.kinds.${v}`) }),
              )}
            />
            <TextField
              label={t("learning.assessments.date")}
              type="date"
              required
              value={form.held_on}
              onChange={(e) => setForm({ ...form, held_on: e.target.value })}
            />
            <TextField
              label={t("learning.assessments.maxScore")}
              inputMode="decimal"
              className="text-right tabular-nums"
              value={form.max_score}
              onChange={(e) => setForm({ ...form, max_score: e.target.value })}
            />
          </FormCard>
          <FormCard
            title={t("learning.assessments.record")}
            submit={t("learning.save")}
            pending={record.isPending}
            error={record.error}
            onSubmit={() => record.mutate()}
          >
            <SelectField
              label={t("learning.assessments.name")}
              required
              value={result.assessment}
              onChange={(e) => setResult({ ...result, assessment: e.target.value })}
              options={[
                { value: "", label: t("learning.assessments.choose") },
                ...(assessments.data?.results ?? []).map((a) => ({ value: a.id, label: a.name })),
              ]}
            />
            <SelectField
              label={t("learning.student")}
              required
              value={result.student}
              onChange={(e) => setResult({ ...result, student: e.target.value })}
              options={options}
            />
            <TextField
              label={t("learning.assessments.score")}
              inputMode="decimal"
              className="text-right tabular-nums"
              value={result.score}
              onChange={(e) => setResult({ ...result, score: e.target.value })}
            />
            <TextField
              label={t("learning.assessments.grade")}
              value={result.grade}
              onChange={(e) => setResult({ ...result, grade: e.target.value })}
            />
          </FormCard>
        </div>
      ) : null}
    </div>
  );
}

// --- progress reports ---------------------------------------------------------------------------

function ProgressSection() {
  const { t, i18n } = useTranslation();
  const invalidate = useInvalidate();
  const canWrite = usePermission("learning.progress.write");
  // Gap G5c (FR-21-6): staff who approve reports set the automatic schedule.
  const canApprove = usePermission("learning.progress.approve");
  const canViewSettings = usePermission("org.settings.view");
  const canSchedule = canApprove && canViewSettings;
  const [selected, setSelected] = useState<string>("");
  const reports = useQuery({
    queryKey: ["learning", "progress"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/learning/progress-reports", { params: { query: PAGE } })),
  });
  const [period, setPeriod] = useState({
    period: "termly" as components["schemas"]["ProgressReportPeriodEnum"],
    period_start: "",
    period_end: "",
  });
  const generate = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/learning/progress-reports/generate", { body: period })),
    onSuccess: invalidate,
  });
  const report = reports.data?.results.find((r) => r.id === selected);
  const list = reports.data?.results ?? [];
  const isPhone = useIsPhone();
  return (
    <div className="space-y-6">
      <Table
        caption={t("learning.tabs.progress")}
        loading={reports.isPending}
        empty={reports.data && !list.length ? t("learning.progress.none") : undefined}
        columns={[
          { header: t("learning.student") },
          ...(isPhone ? [] : [{ header: t("learning.progress.period") }]),
          { header: t("learning.progress.status") },
          { header: t("learning.progress.open"), hidden: true },
        ]}
      >
        {list.map((r) => (
          <tr key={r.id}>
            <td className="font-medium">
              {r.student_name}
              {isPhone ? (
                <span className="block text-xs font-normal text-muted-foreground tabular-nums">
                  {formatDate(r.period_start, i18n.language)} –{" "}
                  {formatDate(r.period_end, i18n.language)}
                </span>
              ) : null}
            </td>
            {isPhone ? null : (
              <td className="tabular-nums">
                {formatDate(r.period_start, i18n.language)} –{" "}
                {formatDate(r.period_end, i18n.language)}
              </td>
            )}
            <td>
              <ProgressStatus status={r.status} />
            </td>
            <td className="py-1.5 text-right">
              <Button
                type="button"
                size="sm"
                variant="secondary"
                aria-pressed={selected === r.id}
                className="aria-pressed:bg-muted"
                onClick={() => setSelected(selected === r.id ? "" : r.id)}
              >
                {t("learning.progress.open")}
              </Button>
            </td>
          </tr>
        ))}
      </Table>
      {report ? <ProgressEditor key={report.id} report={report} /> : null}
      {canWrite ? (
        <FormCard
          title={t("learning.progress.generate")}
          submit={t("learning.progress.generateIt")}
          pending={generate.isPending}
          error={generate.error}
          onSubmit={() => generate.mutate()}
          columns={3}
        >
          <SelectField
            label={t("learning.progress.periodKind")}
            value={period.period}
            onChange={(e) =>
              setPeriod({
                ...period,
                period: e.target.value as components["schemas"]["ProgressReportPeriodEnum"],
              })
            }
            options={(["termly", "monthly", "custom"] as const).map((v) => ({
              value: v,
              label: t(`learning.progress.periods.${v}`),
            }))}
          />
          <TextField
            label={t("learning.progress.from")}
            type="date"
            required
            value={period.period_start}
            onChange={(e) => setPeriod({ ...period, period_start: e.target.value })}
          />
          <TextField
            label={t("learning.progress.to")}
            type="date"
            required
            value={period.period_end}
            onChange={(e) => setPeriod({ ...period, period_end: e.target.value })}
          />
          {generate.data ? (
            <p role="status" className="text-sm sm:col-span-full">
              {t("learning.progress.generated", generate.data)}
            </p>
          ) : null}
        </FormCard>
      ) : null}
      {canSchedule ? (
        <RuledPanel
          titleId="progress-schedule"
          title={t("g5c.progressSchedule.title")}
          description={t("g5c.progressSchedule.intro")}
        >
          <KeyedSettings
            area="learning"
            keys={["learning.progress_schedule"]}
            label={t("g5c.progressSchedule.title")}
          />
        </RuledPanel>
      ) : null}
    </div>
  );
}

export function ProgressEditor({ report }: { report: ProgressReport }) {
  const { t } = useTranslation();
  const invalidate = useInvalidate();
  const canApprove = usePermission("learning.progress.approve");
  const [summary, setSummary] = useState(report.summary);
  const save = useMutation({
    mutationFn: async () => {
      const saved = unwrap(
        await api.PATCH("/api/v1/learning/progress-reports/{id}", {
          params: { path: { id: report.id } },
          body: { summary },
        }),
      );
      if (draft.data) await markAssisted(draft.data.request, "progress_report", report.id);
      return saved;
    },
    onSuccess: invalidate,
  });
  const act = useMutation({
    mutationFn: async (step: "submit" | "approve" | "share" | "reopen" | "regenerate") => {
      const params = { params: { path: { id: report.id } } };
      switch (step) {
        case "submit":
          return unwrap(await api.POST("/api/v1/learning/progress-reports/{id}/submit", params));
        case "approve":
          return unwrap(await api.POST("/api/v1/learning/progress-reports/{id}/approve", params));
        case "share":
          return unwrap(await api.POST("/api/v1/learning/progress-reports/{id}/share", params));
        case "reopen":
          return unwrap(await api.POST("/api/v1/learning/progress-reports/{id}/reopen", params));
        default:
          return unwrap(
            await api.POST("/api/v1/learning/progress-reports/{id}/regenerate", params),
          );
      }
    },
    onSuccess: invalidate,
  });
  // E31: the AI draft comes with a request id for feedback and the AI-assisted flag.
  const draft = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/ai/progress-reports/{report_id}/draft", {
          params: { path: { report_id: report.id } },
        }),
      ),
    onSuccess: (body) => setSummary(body.summary),
  });
  const snap = report.snapshot as {
    attendance?: { lessons: number; attended: number; rate: string | null };
    topics?: { covered: { name: string }[] };
    homework?: { due: number; on_time: number };
  };
  const editable = report.status === "draft" || report.status === "submitted";
  const primary: { step: "submit" | "approve" | "share"; label: string } | null =
    canApprove && report.status === "approved"
      ? { step: "share", label: t("learning.progress.share") }
      : canApprove && (report.status === "submitted" || report.status === "draft")
        ? { step: "approve", label: t("learning.progress.approve") }
        : report.status === "draft"
          ? { step: "submit", label: t("learning.progress.submit") }
          : null;
  return (
    <RuledPanel
      flush
      title={report.title}
      aside={<ProgressStatus status={report.status} />}
      footer={
        <>
          {editable ? (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              loading={save.isPending}
              onClick={() => save.mutate()}
            >
              {t("learning.save")}
            </Button>
          ) : null}
          {editable && report.ai_draft_available ? (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              loading={draft.isPending}
              onClick={() => draft.mutate()}
            >
              {t("learning.progress.aiDraft")}
            </Button>
          ) : null}
          {report.status === "draft" ? (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => act.mutate("regenerate")}
            >
              {t("learning.progress.refresh")}
            </Button>
          ) : null}
          {canApprove && report.status === "draft" ? (
            <Button type="button" size="sm" variant="secondary" onClick={() => act.mutate("submit")}>
              {t("learning.progress.submit")}
            </Button>
          ) : null}
          {report.status === "submitted" || report.status === "approved" ? (
            <Button type="button" size="sm" variant="secondary" onClick={() => act.mutate("reopen")}>
              {t("learning.progress.reopen")}
            </Button>
          ) : null}
          <a
            className={buttonClass({ variant: "secondary", size: "sm" })}
            href={`/api/v1/learning/progress-reports/${report.id}/pdf`}
            target="_blank"
            rel="noreferrer"
          >
            {t("learning.progress.pdf")}
          </a>
          {primary ? (
            <Button
              type="button"
              size="sm"
              loading={act.isPending && act.variables === primary.step}
              onClick={() => act.mutate(primary.step)}
            >
              {primary.label}
            </Button>
          ) : null}
        </>
      }
    >
      <p className="border-b border-rule px-5 py-2.5 text-sm text-muted-foreground tabular-nums">
        {[
          t("learning.progress.attendance", {
            attended: snap.attendance?.attended ?? 0,
            lessons: snap.attendance?.lessons ?? 0,
          }),
          t("learning.progress.topics", { count: snap.topics?.covered.length ?? 0 }),
          t("learning.progress.homework", {
            done: snap.homework?.on_time ?? 0,
            due: snap.homework?.due ?? 0,
          }),
        ].join(" · ")}
      </p>
      <div className="space-y-3 px-5 py-4">
        {editable ? (
          <TextArea
            label={t("learning.progress.summary")}
            value={summary}
            onChange={setSummary}
            rows={5}
          />
        ) : (
          <p className="max-w-prose text-sm whitespace-pre-wrap">{report.summary}</p>
        )}
        <AiAssistedBadge subjectType="progress_report" subjectId={report.id} />
        {draft.data ? (
          <AiFeedback
            request={draft.data.request}
            draftText={draft.data.summary}
            finalText={summary}
          />
        ) : null}
        {editable ? (
          <AiExplainToParent text={summary} student={report.student} onUse={setSummary} />
        ) : null}
        {save.error || act.error || draft.error ? (
          <Alert tone="danger">{(save.error ?? act.error ?? draft.error)?.message}</Alert>
        ) : null}
      </div>
    </RuledPanel>
  );
}

/** A progress report's state in words: margin red while it waits for approval. */
function ProgressStatus({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <span
      className={
        status === "submitted"
          ? "font-semibold text-margin"
          : status === "shared"
            ? "text-muted-foreground"
            : undefined
      }
    >
      {t(`learning.progress.statuses.${status}`)}
    </span>
  );
}

// --- library ------------------------------------------------------------------------------------

function LibrarySection() {
  const { t, i18n } = useTranslation();
  const isPhone = useIsPhone();
  const invalidate = useInvalidate();
  const canManage = usePermission("learning.library.manage");
  const options = useStudentOptions();
  const { data: org } = useOrganisation();
  const items = useQuery({
    queryKey: ["learning", "items"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/library-items", {
          params: { query: { ...PAGE, archived: false } },
        }),
      ),
  });
  const loans = useQuery({
    queryKey: ["learning", "loans"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/learning/loans", { params: { query: { ...PAGE, status: "out" } } }),
      ),
  });
  const [item, setItem] = useState({
    name: "",
    kind: "book" as components["schemas"]["LibraryItemKindEnum"],
    quantity: "1",
    cost: "",
  });
  const createItem = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/library-items", {
          body: {
            name: item.name,
            kind: item.kind,
            quantity: Number(item.quantity) || 1,
            replacement_cost:
              item.cost && org?.default_currency
                ? { amount: item.cost, currency: org.default_currency }
                : null,
          },
        }),
      ),
    onSuccess: () => {
      setItem((x) => ({ ...x, name: "", cost: "" }));
      void invalidate();
    },
  });
  const [loan, setLoan] = useState({ item: "", student: "", due_date: "" });
  const lend = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/loans", {
          body: { item: loan.item, student: loan.student, due_date: loan.due_date || null },
        }),
      ),
    onSuccess: () => {
      setLoan({ item: "", student: "", due_date: "" });
      void invalidate();
    },
  });
  const itemRows = items.data?.results ?? [];
  const loanRows = loans.data?.results ?? [];
  return (
    <div className="space-y-6">
      <Table
        caption={t("learning.library.items")}
        loading={items.isPending}
        empty={items.data && !itemRows.length ? t("learning.library.none") : undefined}
        columns={[
          { header: t("learning.library.name") },
          ...(isPhone
            ? []
            : [
                { header: t("learning.library.kind") },
                { header: t("learning.library.available"), end: true, width: "w-24" },
              ]),
          { header: t("learning.library.cost"), end: true, width: isPhone ? "w-24" : "w-32" },
        ]}
      >
        {itemRows.map((x) => (
          <tr key={x.id}>
            <td className="font-medium">
              {x.name}
              {isPhone ? (
                <span className="block text-xs font-normal text-muted-foreground tabular-nums">
                  {t(`learning.library.kinds.${x.kind}`)} ·{" "}
                  {t("learning.library.availableOf", { available: x.available, total: x.quantity })}
                </span>
              ) : null}
            </td>
            {isPhone ? null : (
              <>
                <td>{t(`learning.library.kinds.${x.kind}`)}</td>
                <td className={figureCell}>
                  {t("learning.library.availableOf", {
                    available: x.available,
                    total: x.quantity,
                  })}
                </td>
              </>
            )}
            <td className={figureCell}>
              {x.replacement_cost ? (
                formatMoney(x.replacement_cost, i18n.language)
              ) : (
                <span className="text-muted-foreground">–</span>
              )}
            </td>
          </tr>
        ))}
      </Table>
      <Table
        caption={t("learning.library.onLoan")}
        loading={loans.isPending}
        empty={loans.data && !loanRows.length ? t("designS6.learning.nothingOnLoan") : undefined}
        columns={[
          { header: t("learning.library.name") },
          ...(isPhone
            ? []
            : [{ header: t("learning.student") }, { header: t("learning.library.due") }]),
          { header: t("common.actions"), hidden: true },
        ]}
      >
        {loanRows.map((x) => (
          <LoanRow key={x.id} loan={x} />
        ))}
      </Table>
      {canManage ? (
        <div className="grid items-start gap-6 lg:grid-cols-2">
          <FormCard
            title={t("learning.library.lend")}
            submit={t("learning.library.lendIt")}
            pending={lend.isPending}
            error={lend.error}
            onSubmit={() => lend.mutate()}
          >
            <SelectField
              label={t("learning.library.name")}
              required
              value={loan.item}
              onChange={(e) => setLoan({ ...loan, item: e.target.value })}
              options={[
                { value: "", label: t("learning.library.chooseItem") },
                ...(items.data?.results ?? []).map((x) => ({ value: x.id, label: x.name })),
              ]}
            />
            <SelectField
              label={t("learning.student")}
              required
              value={loan.student}
              onChange={(e) => setLoan({ ...loan, student: e.target.value })}
              options={options}
            />
            <TextField
              label={t("learning.library.due")}
              type="date"
              value={loan.due_date}
              onChange={(e) => setLoan({ ...loan, due_date: e.target.value })}
            />
          </FormCard>
          <FormCard
            title={t("learning.library.newItem")}
            submit={t("learning.add")}
            pending={createItem.isPending}
            error={createItem.error}
            onSubmit={() => createItem.mutate()}
          >
            <TextField
              label={t("learning.library.name")}
              required
              value={item.name}
              onChange={(e) => setItem({ ...item, name: e.target.value })}
            />
            <SelectField
              label={t("learning.library.kind")}
              value={item.kind}
              onChange={(e) =>
                setItem({
                  ...item,
                  kind: e.target.value as components["schemas"]["LibraryItemKindEnum"],
                })
              }
              options={(["book", "instrument", "device", "other"] as const).map((v) => ({
                value: v,
                label: t(`learning.library.kinds.${v}`),
              }))}
            />
            <TextField
              label={t("learning.library.quantity")}
              type="number"
              min={1}
              value={item.quantity}
              onChange={(e) => setItem({ ...item, quantity: e.target.value })}
            />
            <TextField
              label={t("learning.library.cost")}
              inputMode="decimal"
              className="text-right tabular-nums"
              value={item.cost}
              onChange={(e) => setItem({ ...item, cost: e.target.value })}
            />
          </FormCard>
        </div>
      ) : null}
    </div>
  );
}

function LoanRow({ loan }: { loan: Loan }) {
  const { t, i18n } = useTranslation();
  const isPhone = useIsPhone();
  const invalidate = useInvalidate();
  const canManage = usePermission("learning.library.manage");
  const canCharge = usePermission("learning.library.charge");
  const act = useMutation({
    mutationFn: async (step: "return" | "lost" | "charge") =>
      step === "return"
        ? unwrap(
            await api.POST("/api/v1/learning/loans/{id}/return", {
              params: { path: { id: loan.id } },
              body: {},
            }),
          )
        : unwrap(
            await api.POST("/api/v1/learning/loans/{id}/lost", {
              params: { path: { id: loan.id }, header: { "Idempotency-Key": `lost-${loan.id}` } },
              body: { charge: step === "charge" },
            }),
          ),
    onSuccess: invalidate,
  });
  return (
    <tr>
      <td className="font-medium">
        {loan.item_name}
        {isPhone ? (
          <span className="block text-xs font-normal text-muted-foreground tabular-nums">
            {loan.student_name} · {formatDate(loan.due_date, i18n.language)}
            {loan.is_overdue ? (
              <>
                {" · "}
                <span className="font-semibold text-margin">{t("learning.library.overdue")}</span>
              </>
            ) : null}
          </span>
        ) : null}
      </td>
      {isPhone ? null : (
        <>
          <td>{loan.student_name}</td>
          <td className="tabular-nums">
            {formatDate(loan.due_date, i18n.language)}
            {loan.is_overdue ? (
              <span className="block text-xs font-semibold text-margin">
                {t("learning.library.overdue")}
              </span>
            ) : null}
          </td>
        </>
      )}
      <td className="py-1.5 text-right">
        {canManage ? (
          <span className="inline-flex flex-wrap justify-end gap-2">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              loading={act.isPending && act.variables === "return"}
              onClick={() => act.mutate("return")}
            >
              {t("learning.library.returned")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="text-muted-foreground"
              onClick={() => act.mutate("lost")}
            >
              {t("learning.library.lost")}
            </Button>
            {canCharge ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="text-muted-foreground"
                onClick={() => act.mutate("charge")}
              >
                {t("learning.library.lostCharge")}
              </Button>
            ) : null}
          </span>
        ) : null}
        {act.error ? (
          <Alert tone="danger" className="mt-2 text-left">
            {act.error.message}
          </Alert>
        ) : null}
      </td>
    </tr>
  );
}

// --- quizzes ------------------------------------------------------------------------------------

interface DraftQuestion {
  kind: QuestionKind;
  prompt: string;
  choices: string;
  answer: string;
}

function QuizzesSection() {
  const { t } = useTranslation();
  const isPhone = useIsPhone();
  const invalidate = useInvalidate();
  const canManage = usePermission("learning.quiz.manage");
  const quizzes = useQuery({
    queryKey: ["learning", "quizzes"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/learning/quizzes", { params: { query: PAGE } })),
  });
  const [title, setTitle] = useState("");
  // G5a (FR-18-3): a quiz can be a tutor subject test, with a subject and a pass mark.
  const [purpose, setPurpose] = useState<"learning" | "tutor_test">("learning");
  const [subject, setSubject] = useState("");
  const [passPercent, setPassPercent] = useState("50");
  const subjects = useQuery({
    queryKey: ["g3", "subjects"],
    enabled: canManage,
    queryFn: async () => {
      const rows = unwrap(await api.GET("/api/v1/catalogue/subjects"));
      return ("results" in rows ? rows.results : rows) as { id: string; name: string }[];
    },
  });
  const [questions, setQuestions] = useState<DraftQuestion[]>([
    { kind: "single", prompt: "", choices: "", answer: "" },
  ]);
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/quizzes", {
          body: {
            title,
            purpose,
            subject: subject || null,
            pass_percent: Number(passPercent),
            questions: questions.map((q) => {
              const choices = q.choices
                .split("\n")
                .map((c) => c.trim())
                .filter(Boolean)
                .map((text, i) => ({ id: String.fromCharCode(97 + i), text }));
              const answers = q.answer
                .split(",")
                .map((a) => a.trim())
                .filter(Boolean);
              return {
                kind: q.kind,
                prompt: q.prompt,
                choices: q.kind === "short" ? [] : choices,
                answer: q.kind === "short" ? answers : answers.map((a) => a.toLowerCase()),
              };
            }),
          },
        }),
      ),
    onSuccess: () => {
      setTitle("");
      setPurpose("learning");
      setSubject("");
      setQuestions([{ kind: "single", prompt: "", choices: "", answer: "" }]);
      void invalidate();
    },
  });
  const update = (i: number, change: Partial<DraftQuestion>) =>
    setQuestions((qs) => qs.map((q, j) => (j === i ? { ...q, ...change } : q)));
  const list = quizzes.data?.results ?? [];
  return (
    <div className="space-y-6">
      <Table
        caption={t("learning.tabs.quizzes")}
        loading={quizzes.isPending}
        empty={quizzes.data && !list.length ? t("learning.quizzes.none") : undefined}
        columns={[
          { header: t("learning.quizzes.titleLabel") },
          ...(isPhone ? [] : [{ header: t("hiring.tests.purpose") }]),
          { header: t("learning.quizzes.questions"), end: true, width: "w-24" },
          { header: t("learning.quizzes.attempts"), end: true, width: "w-24" },
        ]}
      >
        {list.map((q) => (
          <tr key={q.id}>
            <td className="font-medium">
              {q.title}
              {isPhone ? (
                <span className="block text-xs font-normal text-muted-foreground">
                  {t(`hiring.tests.purposes.${q.purpose ?? "learning"}`)}
                </span>
              ) : null}
            </td>
            {isPhone ? null : <td>{t(`hiring.tests.purposes.${q.purpose ?? "learning"}`)}</td>}
            <td className={figureCell}>{q.questions?.length ?? 0}</td>
            <td className={figureCell}>{q.attempts_count}</td>
          </tr>
        ))}
      </Table>
      {canManage ? (
        <FormCard
          title={t("learning.quizzes.new")}
          submit={t("learning.add")}
          pending={create.isPending}
          error={create.error}
          onSubmit={() => create.mutate()}
          lead={
            <Button
              type="button"
              variant="secondary"
              onClick={() =>
                setQuestions((qs) => [
                  ...qs,
                  { kind: "single", prompt: "", choices: "", answer: "" },
                ])
              }
            >
              {t("learning.quizzes.addQuestion")}
            </Button>
          }
        >
          <TextField
            label={t("learning.quizzes.titleLabel")}
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <SelectField
            label={t("hiring.tests.purpose")}
            hint={purpose === "tutor_test" ? t("hiring.tests.purposeHint") : undefined}
            value={purpose}
            onChange={(e) => setPurpose(e.target.value as "learning" | "tutor_test")}
            options={(["learning", "tutor_test"] as const).map((v) => ({
              value: v,
              label: t(`hiring.tests.purposes.${v}`),
            }))}
          />
          <SelectField
            label={t("hiring.tests.subject")}
            required={purpose === "tutor_test"}
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            options={[
              { value: "", label: t("hiring.tests.anySubject") },
              ...(subjects.data ?? []).map((sub) => ({ value: sub.id, label: sub.name })),
            ]}
          />
          <TextField
            label={t("hiring.tests.passMark")}
            type="number"
            className="text-right tabular-nums"
            min={0}
            max={100}
            value={passPercent}
            onChange={(e) => setPassPercent(e.target.value)}
          />
          {questions.map((q, i) => (
            <fieldset
              key={i}
              className="-mx-5 grid gap-x-4 gap-y-3 border-t border-rule px-5 pt-4 sm:col-span-full sm:grid-cols-2"
            >
              <legend className="float-left mb-1 w-full text-base font-semibold sm:col-span-full">
                {t("learning.quizzes.questionN", { n: i + 1 })}
              </legend>
              <SelectField
                label={t("learning.quizzes.kind")}
                value={q.kind}
                onChange={(e) => update(i, { kind: e.target.value as QuestionKind })}
                options={(["single", "multiple", "short"] as const).map((v) => ({
                  value: v,
                  label: t(`learning.quizzes.kinds.${v}`),
                }))}
              />
              <TextArea
                label={t("learning.quizzes.prompt")}
                required
                value={q.prompt}
                onChange={(value) => update(i, { prompt: value })}
              />
              {q.kind !== "short" ? (
                <TextArea
                  label={t("learning.quizzes.choices")}
                  value={q.choices}
                  onChange={(value) => update(i, { choices: value })}
                />
              ) : null}
              <TextField
                label={t("learning.quizzes.answer")}
                hint={t(
                  q.kind === "short"
                    ? "learning.quizzes.answerShortHint"
                    : "learning.quizzes.answerChoiceHint",
                )}
                value={q.answer}
                onChange={(e) => update(i, { answer: e.target.value })}
              />
            </fieldset>
          ))}
        </FormCard>
      ) : null}
    </div>
  );
}
