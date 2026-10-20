import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, useOrganisation, usePermission } from "../api";
import { markAssisted } from "../ai/ai";
import { AiAssistedBadge, AiFeedback } from "../ai/AiParts";
import { AiExplainToParent } from "../ai/AiWidgets";
import { PAGE, localToIso, uploadFile, useStudentOptions } from "./hooks";
import { Cell, Empty, FormCard, Table, TextArea } from "./shared";

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
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("learning.title")}</h1>
      <div className="flex flex-wrap items-end gap-2">
        <SelectField
          label={t("learning.studentProgress")}
          value={student}
          onChange={(e) => setStudent(e.target.value)}
          options={options}
        />
        {student ? (
          <Link
            to="/learning/students/$studentId"
            params={{ studentId: student }}
            className="pb-2 text-sm underline"
          >
            {t("learning.openStudent")}
          </Link>
        ) : null}
      </div>
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
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">{t("learning.homework.toReview")}</h2>
      {toReview.data && !toReview.data.results.length ? (
        <Empty>{t("learning.homework.nothingToReview")}</Empty>
      ) : null}
      {toReview.data?.results.map((a) => (
        <ReviewCard key={a.id} assignment={a} />
      ))}
      {homework.isLoading ? <Spinner label={t("grid.loading")} /> : null}
      {homework.data?.results.length ? (
        <Table
          caption={t("learning.homework.set")}
          headers={[
            t("learning.homework.titleLabel"),
            t("learning.homework.due"),
            t("learning.homework.progress"),
            t("learning.homework.setBy"),
          ]}
        >
          {homework.data.results.map((h) => (
            <tr key={h.id}>
              <Cell>{h.title}</Cell>
              <Cell>{formatDateTime(h.due_at, i18n.language)}</Cell>
              <Cell>
                {t("learning.homework.counts", {
                  submitted: h.counts.submitted,
                  completed: h.counts.completed,
                  total: h.counts.total,
                  overdue: h.counts.overdue,
                })}
              </Cell>
              <Cell>{h.set_by_name}</Cell>
            </tr>
          ))}
        </Table>
      ) : homework.data ? (
        <Empty>{t("learning.homework.none")}</Empty>
      ) : null}
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
      className="space-y-2 rounded-md border border-border p-3"
    >
      <h3 className="font-medium">
        {assignment.homework_title} · {assignment.student_name}
      </h3>
      {latest ? (
        <div className="text-sm">
          <p className="text-muted-foreground">
            {t("learning.homework.handedIn", {
              when: formatDateTime(latest.created_at, i18n.language),
            })}
            {latest.is_late ? ` · ${t("learning.homework.late")}` : ""}
          </p>
          {latest.body ? <p className="whitespace-pre-wrap">{latest.body}</p> : null}
          {latest.link ? (
            <a className="underline" href={latest.link} rel="noreferrer noopener" target="_blank">
              {latest.link}
            </a>
          ) : null}
          {latest.files.map((f) => (
            <p key={f.id}>{f.filename}</p>
          ))}
        </div>
      ) : null}
      <div className="grid gap-2 sm:grid-cols-2">
        <TextField
          label={t("learning.homework.grade")}
          value={grade}
          onChange={(e) => setGrade(e.target.value)}
        />
        <TextArea label={t("learning.homework.feedback")} value={feedback} onChange={setFeedback} />
      </div>
      {review.error ? <Alert tone="danger">{review.error.message}</Alert> : null}
      <div className="flex gap-2">
        <Button type="button" disabled={review.isPending} onClick={() => review.mutate("complete")}>
          {t("learning.homework.markComplete")}
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={review.isPending}
          onClick={() => review.mutate("resubmit")}
        >
          {t("learning.homework.returnIt")}
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
  return (
    <div className="space-y-6">
      {storage.data ? (
        <p className="text-sm text-muted-foreground">
          {storage.data.limit_gb
            ? t("learning.resources.storage", {
                used: (storage.data.used_bytes / 1024 ** 3).toFixed(2),
                limit: storage.data.limit_gb,
              })
            : t("learning.resources.storageUnlimited", {
                used: (storage.data.used_bytes / 1024 ** 3).toFixed(2),
              })}
        </p>
      ) : null}
      <TextField label={t("learning.search")} value={q} onChange={(e) => setQ(e.target.value)} />
      {resources.data && !resources.data.results.length ? (
        <Empty>{t("learning.resources.none")}</Empty>
      ) : null}
      {resources.data?.results.length ? (
        <Table
          caption={t("learning.tabs.resources")}
          headers={[
            t("learning.resources.titleLabel"),
            t("learning.resources.type"),
            t("learning.resources.library"),
            t("learning.resources.shared"),
            "",
          ]}
        >
          {resources.data.results.map((r) => (
            <ResourceRow key={r.id} resource={r} />
          ))}
        </Table>
      ) : null}
      {canManage ? <NewResourceForm /> : null}
    </div>
  );
}

function ResourceRow({ resource }: { resource: Resource }) {
  const { t } = useTranslation();
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
  return (
    <tr>
      <Cell>
        <button type="button" className="text-left underline" onClick={() => open.mutate()}>
          {resource.title}
        </button>
        {resource.tags?.length ? (
          <span className="block text-xs text-muted-foreground">{resource.tags.join(", ")}</span>
        ) : null}
      </Cell>
      <Cell>{t(`learning.resources.media.${resource.media_type}`)}</Cell>
      <Cell>{resource.owner_name || t("learning.resources.orgLibrary")}</Cell>
      <Cell>{resource.share_count}</Cell>
      <Cell>
        {canShare ? (
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (student) share.mutate();
            }}
          >
            <SelectField
              label={t("learning.resources.shareWith", { title: resource.title })}
              value={student}
              onChange={(e) => setStudent(e.target.value)}
              options={options}
            />
            <Button type="submit" size="sm" disabled={!student || share.isPending}>
              {t("learning.resources.share")}
            </Button>
          </form>
        ) : null}
        {share.error ? <Alert tone="danger">{share.error.message}</Alert> : null}
      </Cell>
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
  return (
    <div className="space-y-6">
      {curricula.data?.results.length ? (
        <Table
          caption={t("learning.tabs.curricula")}
          headers={[t("learning.curricula.name"), t("learning.curricula.topics"), ""]}
        >
          {curricula.data.results.map((c) => (
            <tr key={c.id}>
              <Cell>{c.name}</Cell>
              <Cell>{c.topic_count}</Cell>
              <Cell>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => setSelected(c.id)}
                >
                  {t("learning.curricula.open")}
                </Button>
              </Cell>
            </tr>
          ))}
        </Table>
      ) : curricula.data ? (
        <Empty>{t("learning.curricula.none")}</Empty>
      ) : null}
      {selected ? <CurriculumTree id={selected} canManage={canManage} /> : null}
      {canManage ? (
        <>
          <section className="space-y-2">
            <h2 className="font-semibold">{t("learning.curricula.builtins")}</h2>
            <ul className="space-y-1 text-sm">
              {builtins.data?.map((b) => (
                <li key={b.key} className="flex items-center gap-2">
                  <span>
                    {b.name} ({t("learning.curricula.size", { units: b.units, topics: b.topics })})
                  </span>
                  {b.installed ? (
                    <span className="text-muted-foreground">
                      {t("learning.curricula.installed")}
                    </span>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      disabled={install.isPending}
                      onClick={() => install.mutate(b.key)}
                    >
                      {t("learning.curricula.install", { name: b.name })}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
            {install.error ? <Alert tone="danger">{install.error.message}</Alert> : null}
          </section>
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

function CurriculumTree({ id, canManage }: { id: string; canManage: boolean }) {
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
    <section className="space-y-3 rounded-md border border-border p-4">
      {tree.data?.map((unit) => (
        <div key={unit.id}>
          <h3 className="font-medium">
            {unit.code ? `${unit.code} ` : ""}
            {unit.name}
          </h3>
          <ul className="ml-4 list-disc text-sm">
            {unit.topics.map((topic) => (
              <li key={topic.id}>
                {topic.code ? `${topic.code} ` : ""}
                {topic.name}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {canManage ? (
        <TextField
          label={t("learning.curricula.importCsv")}
          hint={t("learning.curricula.csvHint")}
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) importCsv.mutate(file);
          }}
        />
      ) : null}
      {importCsv.data ? (
        <p role="status" className="text-sm">
          {t("learning.curricula.imported", importCsv.data)}
        </p>
      ) : null}
      {importCsv.error ? <Alert tone="danger">{importCsv.error.message}</Alert> : null}
    </section>
  );
}

// --- assessments --------------------------------------------------------------------------------

function AssessmentsSection() {
  const { t, i18n } = useTranslation();
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
  return (
    <div className="space-y-6">
      {assessments.data?.results.length ? (
        <Table
          caption={t("learning.tabs.assessments")}
          headers={[
            t("learning.assessments.name"),
            t("learning.assessments.kind"),
            t("learning.assessments.date"),
            t("learning.assessments.results"),
          ]}
        >
          {assessments.data.results.map((a) => (
            <tr key={a.id}>
              <Cell>{a.name}</Cell>
              <Cell>{t(`learning.assessments.kinds.${a.kind}`)}</Cell>
              <Cell>{formatDate(a.held_on, i18n.language)}</Cell>
              <Cell>{a.results_count}</Cell>
            </tr>
          ))}
        </Table>
      ) : assessments.data ? (
        <Empty>{t("learning.assessments.none")}</Empty>
      ) : null}
      {canManage ? (
        <>
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
              value={result.score}
              onChange={(e) => setResult({ ...result, score: e.target.value })}
            />
            <TextField
              label={t("learning.assessments.grade")}
              value={result.grade}
              onChange={(e) => setResult({ ...result, grade: e.target.value })}
            />
          </FormCard>
        </>
      ) : null}
    </div>
  );
}

// --- progress reports ---------------------------------------------------------------------------

function ProgressSection() {
  const { t, i18n } = useTranslation();
  const invalidate = useInvalidate();
  const canWrite = usePermission("learning.progress.write");
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
  return (
    <div className="space-y-6">
      {reports.data?.results.length ? (
        <Table
          caption={t("learning.tabs.progress")}
          headers={[
            t("learning.student"),
            t("learning.progress.period"),
            t("learning.progress.status"),
            "",
          ]}
        >
          {reports.data.results.map((r) => (
            <tr key={r.id}>
              <Cell>{r.student_name}</Cell>
              <Cell>
                {formatDate(r.period_start, i18n.language)} –{" "}
                {formatDate(r.period_end, i18n.language)}
              </Cell>
              <Cell>{t(`learning.progress.statuses.${r.status}`)}</Cell>
              <Cell>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => setSelected(r.id)}
                >
                  {t("learning.progress.open")}
                </Button>
              </Cell>
            </tr>
          ))}
        </Table>
      ) : reports.data ? (
        <Empty>{t("learning.progress.none")}</Empty>
      ) : null}
      {report ? <ProgressEditor key={report.id} report={report} /> : null}
      {canWrite ? (
        <FormCard
          title={t("learning.progress.generate")}
          submit={t("learning.progress.generateIt")}
          pending={generate.isPending}
          error={generate.error}
          onSubmit={() => generate.mutate()}
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
            <p role="status" className="text-sm sm:col-span-2">
              {t("learning.progress.generated", generate.data)}
            </p>
          ) : null}
        </FormCard>
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
  return (
    <section aria-label={report.title} className="space-y-3 rounded-md border border-border p-4">
      <h2 className="font-semibold">{report.title}</h2>
      <ul className="text-sm">
        <li>
          {t("learning.progress.attendance", {
            attended: snap.attendance?.attended ?? 0,
            lessons: snap.attendance?.lessons ?? 0,
          })}
        </li>
        <li>{t("learning.progress.topics", { count: snap.topics?.covered.length ?? 0 })}</li>
        <li>
          {t("learning.progress.homework", {
            done: snap.homework?.on_time ?? 0,
            due: snap.homework?.due ?? 0,
          })}
        </li>
      </ul>
      {editable ? (
        <TextArea label={t("learning.progress.summary")} value={summary} onChange={setSummary} />
      ) : (
        <p className="whitespace-pre-wrap text-sm">{report.summary}</p>
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
      <div className="flex flex-wrap gap-2">
        {editable ? (
          <Button type="button" variant="secondary" onClick={() => save.mutate()}>
            {t("learning.save")}
          </Button>
        ) : null}
        {editable && report.ai_draft_available ? (
          <Button type="button" variant="secondary" onClick={() => draft.mutate()}>
            {t("learning.progress.aiDraft")}
          </Button>
        ) : null}
        {report.status === "draft" ? (
          <>
            <Button type="button" variant="secondary" onClick={() => act.mutate("regenerate")}>
              {t("learning.progress.refresh")}
            </Button>
            <Button type="button" onClick={() => act.mutate("submit")}>
              {t("learning.progress.submit")}
            </Button>
          </>
        ) : null}
        {canApprove && (report.status === "submitted" || report.status === "draft") ? (
          <Button type="button" onClick={() => act.mutate("approve")}>
            {t("learning.progress.approve")}
          </Button>
        ) : null}
        {canApprove && report.status === "approved" ? (
          <Button type="button" onClick={() => act.mutate("share")}>
            {t("learning.progress.share")}
          </Button>
        ) : null}
        {report.status === "submitted" || report.status === "approved" ? (
          <Button type="button" variant="secondary" onClick={() => act.mutate("reopen")}>
            {t("learning.progress.reopen")}
          </Button>
        ) : null}
        <a
          className="self-center text-sm underline"
          href={`/api/v1/learning/progress-reports/${report.id}/pdf`}
          target="_blank"
          rel="noreferrer"
        >
          {t("learning.progress.pdf")}
        </a>
      </div>
    </section>
  );
}

// --- library ------------------------------------------------------------------------------------

function LibrarySection() {
  const { t, i18n } = useTranslation();
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
  return (
    <div className="space-y-6">
      {items.data?.results.length ? (
        <Table
          caption={t("learning.library.items")}
          headers={[
            t("learning.library.name"),
            t("learning.library.kind"),
            t("learning.library.available"),
            t("learning.library.cost"),
          ]}
        >
          {items.data.results.map((x) => (
            <tr key={x.id}>
              <Cell>{x.name}</Cell>
              <Cell>{t(`learning.library.kinds.${x.kind}`)}</Cell>
              <Cell>
                {t("learning.library.availableOf", { available: x.available, total: x.quantity })}
              </Cell>
              <Cell>
                {x.replacement_cost ? formatMoney(x.replacement_cost, i18n.language) : ""}
              </Cell>
            </tr>
          ))}
        </Table>
      ) : items.data ? (
        <Empty>{t("learning.library.none")}</Empty>
      ) : null}
      {loans.data?.results.length ? (
        <Table
          caption={t("learning.library.onLoan")}
          headers={[
            t("learning.library.name"),
            t("learning.student"),
            t("learning.library.due"),
            "",
          ]}
        >
          {loans.data.results.map((x) => (
            <LoanRow key={x.id} loan={x} />
          ))}
        </Table>
      ) : null}
      {canManage ? (
        <>
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
              value={item.cost}
              onChange={(e) => setItem({ ...item, cost: e.target.value })}
            />
          </FormCard>
        </>
      ) : null}
    </div>
  );
}

function LoanRow({ loan }: { loan: Loan }) {
  const { t, i18n } = useTranslation();
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
      <Cell>{loan.item_name}</Cell>
      <Cell>{loan.student_name}</Cell>
      <Cell>
        {formatDate(loan.due_date, i18n.language)}
        {loan.is_overdue ? (
          <span className="ml-1 font-medium text-danger">{t("learning.library.overdue")}</span>
        ) : null}
      </Cell>
      <Cell>
        {canManage ? (
          <div className="flex flex-wrap gap-1">
            <Button type="button" size="sm" onClick={() => act.mutate("return")}>
              {t("learning.library.returned")}
            </Button>
            <Button type="button" size="sm" variant="secondary" onClick={() => act.mutate("lost")}>
              {t("learning.library.lost")}
            </Button>
            {canCharge ? (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={() => act.mutate("charge")}
              >
                {t("learning.library.lostCharge")}
              </Button>
            ) : null}
          </div>
        ) : null}
        {act.error ? <Alert tone="danger">{act.error.message}</Alert> : null}
      </Cell>
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
  const invalidate = useInvalidate();
  const canManage = usePermission("learning.quiz.manage");
  const quizzes = useQuery({
    queryKey: ["learning", "quizzes"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/learning/quizzes", { params: { query: PAGE } })),
  });
  const [title, setTitle] = useState("");
  const [questions, setQuestions] = useState<DraftQuestion[]>([
    { kind: "single", prompt: "", choices: "", answer: "" },
  ]);
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/learning/quizzes", {
          body: {
            title,
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
      setQuestions([{ kind: "single", prompt: "", choices: "", answer: "" }]);
      void invalidate();
    },
  });
  const update = (i: number, change: Partial<DraftQuestion>) =>
    setQuestions((qs) => qs.map((q, j) => (j === i ? { ...q, ...change } : q)));
  return (
    <div className="space-y-6">
      {quizzes.data?.results.length ? (
        <Table
          caption={t("learning.tabs.quizzes")}
          headers={[
            t("learning.quizzes.titleLabel"),
            t("learning.quizzes.questions"),
            t("learning.quizzes.attempts"),
          ]}
        >
          {quizzes.data.results.map((q) => (
            <tr key={q.id}>
              <Cell>{q.title}</Cell>
              <Cell>{q.questions?.length ?? 0}</Cell>
              <Cell>{q.attempts_count}</Cell>
            </tr>
          ))}
        </Table>
      ) : quizzes.data ? (
        <Empty>{t("learning.quizzes.none")}</Empty>
      ) : null}
      {canManage ? (
        <FormCard
          title={t("learning.quizzes.new")}
          submit={t("learning.add")}
          pending={create.isPending}
          error={create.error}
          onSubmit={() => create.mutate()}
        >
          <TextField
            label={t("learning.quizzes.titleLabel")}
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          {questions.map((q, i) => (
            <fieldset
              key={i}
              className="space-y-2 rounded-md border border-border p-3 sm:col-span-2"
            >
              <legend className="text-sm font-medium">
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
          <Button
            type="button"
            variant="secondary"
            onClick={() =>
              setQuestions((qs) => [...qs, { kind: "single", prompt: "", choices: "", answer: "" }])
            }
          >
            {t("learning.quizzes.addQuestion")}
          </Button>
        </FormCard>
      ) : null}
    </div>
  );
}
