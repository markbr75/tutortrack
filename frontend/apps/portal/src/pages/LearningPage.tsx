import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, Tabs, TextField, TrendChart } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState } from "react";

import { api, uploadFile } from "../api";

type Homework = components["schemas"]["PortalHomework"];
type Answer = string | string[];

const TABS = ["homework", "resources", "goals", "results", "progress", "loans"] as const;
type Tab = (typeof TABS)[number];

function initialTab(): Tab {
  const wanted = new URLSearchParams(window.location.search).get("tab");
  return (TABS as readonly string[]).includes(wanted ?? "") ? (wanted as Tab) : "homework";
}

/** Homework, shared resources, goals, results, progress reports and loans for the
 * household (E21 on the E15 portal). */
export function LearningPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>(initialTab);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{t("learning.portal.title")}</h1>
      <Tabs
        label={t("learning.portal.title")}
        tabs={TABS.map((key) => ({ key, label: t(`learning.portal.tabs.${key}`) }))}
        value={tab}
        onChange={setTab}
      >
        {tab === "homework" ? <HomeworkList /> : null}
        {tab === "resources" ? <Resources /> : null}
        {tab === "goals" ? <Goals /> : null}
        {tab === "results" ? <Results /> : null}
        {tab === "progress" ? <Progress /> : null}
        {tab === "loans" ? <Loans /> : null}
      </Tabs>
    </div>
  );
}

function Muted({ children }: { children: string }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

function HomeworkList() {
  const { t, i18n } = useTranslation();
  const homework = useQuery({
    queryKey: ["portal", "learning", "homework"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/learning/homework")),
  });
  if (homework.isPending) return <Spinner label={t("grid.loading")} />;
  if (!homework.data?.length) return <Muted>{t("learning.portal.noHomework")}</Muted>;
  return (
    <ul className="space-y-2">
      {homework.data.map((h) => (
        <li key={h.id} className="rounded-lg border border-border p-3">
          <Link
            to="/learning/homework/$assignmentId"
            params={{ assignmentId: h.id }}
            className="font-medium underline"
          >
            {h.title}
          </Link>
          <p className="text-sm text-muted-foreground">
            {h.student_name} ·{" "}
            {t("learning.portal.due", { when: formatDateTime(h.due_at, i18n.language) })}
          </p>
          <p className="text-sm">
            {t(`learning.portal.status.${h.status}`)}
            {h.overdue ? ` · ${t("learning.portal.overdue")}` : ""}
            {h.grade ? ` · ${h.grade}` : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}

/** One piece of homework: instructions, resources, hand-in (text, link, files, quiz or
 * "done") and the tutor's feedback. */
export function HomeworkPage({ assignmentId }: { assignmentId: string }) {
  const { t, i18n } = useTranslation();
  const homework = useQuery({
    queryKey: ["portal", "learning", "homework", assignmentId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/portal/learning/homework/{assignment_id}", {
          params: { path: { assignment_id: assignmentId } },
        }),
      ),
  });
  if (homework.isPending) return <Spinner label={t("grid.loading")} />;
  const h = homework.data;
  if (!h) return <Muted>{t("errors.generic")}</Muted>;
  return (
    <article className="space-y-4" aria-label={h.title}>
      <header>
        <h1 className="text-xl font-semibold">{h.title}</h1>
        <p className="text-sm text-muted-foreground">
          {h.student_name}
          {h.tutor_name ? ` · ${h.tutor_name}` : ""} ·{" "}
          {t("learning.portal.due", { when: formatDateTime(h.due_at, i18n.language) })}
          {h.expected_minutes
            ? ` · ${t("learning.portal.minutes", { n: h.expected_minutes })}`
            : ""}
        </p>
        <p className="text-sm font-medium">
          {t(`learning.portal.status.${h.status}`)}
          {h.overdue ? ` · ${t("learning.portal.overdue")}` : ""}
        </p>
      </header>
      {h.instructions ? <p className="whitespace-pre-wrap">{h.instructions}</p> : null}
      {h.resources.length ? (
        <section>
          <h2 className="font-medium">{t("learning.portal.resources")}</h2>
          <ul className="text-sm">
            {h.resources.map((r) => (
              <li key={r.id}>
                <OpenResource id={r.id} title={r.title} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {h.grade || h.feedback ? (
        <section className="rounded-lg border border-border p-3">
          <h2 className="font-medium">{t("learning.portal.feedback")}</h2>
          {h.grade ? <p>{t("learning.portal.grade", { grade: h.grade })}</p> : null}
          {h.feedback ? <p className="whitespace-pre-wrap">{h.feedback}</p> : null}
        </section>
      ) : null}
      {h.quiz_result ? (
        <p role="status">
          {t(h.quiz_result.passed ? "learning.portal.quizPassed" : "learning.portal.quizScore", {
            percent: h.quiz_result.percent,
          })}
        </p>
      ) : null}
      {h.submissions.length ? (
        <section>
          <h2 className="font-medium">{t("learning.portal.handedIn")}</h2>
          <ul className="space-y-1 text-sm">
            {h.submissions.map((s) => (
              <li key={s.id}>
                {formatDateTime(s.created_at, i18n.language)}
                {s.is_late ? ` · ${t("learning.portal.late")}` : ""}
                {s.body ? ` · ${s.body.slice(0, 80)}` : ""}
                {s.files.map((f) => ` · ${f.filename}`).join("")}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {h.can_submit ? <SubmitForm homework={h} /> : null}
    </article>
  );
}

function SubmitForm({ homework }: { homework: Homework }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const bodyId = useId();
  const [body, setBody] = useState("");
  const [link, setLink] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const submit = useMutation({
    mutationFn: async () => {
      const fileIds = await Promise.all(files.map(uploadFile));
      return unwrap(
        await api.POST("/api/v1/portal/learning/homework/{assignment_id}/submit", {
          params: { path: { assignment_id: homework.id } },
          body: {
            body,
            link,
            files: fileIds,
            ...(homework.submission_type === "quiz" ? { quiz_answers: answers } : {}),
          },
        }),
      );
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["portal", "learning"] }),
  });
  const kind = homework.submission_type;
  return (
    <form
      className="space-y-3 rounded-lg border border-border p-4"
      aria-label={t("learning.portal.handIn")}
      onSubmit={(e) => {
        e.preventDefault();
        submit.mutate();
      }}
    >
      <h2 className="font-semibold">{t("learning.portal.handIn")}</h2>
      {kind === "text" ? (
        <div className="space-y-1">
          <label htmlFor={bodyId} className="text-sm font-medium">
            {t("learning.portal.answer")}
          </label>
          <textarea
            id={bodyId}
            required
            className="min-h-32 w-full rounded-md border border-border bg-background px-3 py-2 text-base"
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
        </div>
      ) : null}
      {kind === "link" ? (
        <TextField
          label={t("learning.portal.link")}
          type="url"
          required
          value={link}
          onChange={(e) => setLink(e.target.value)}
        />
      ) : null}
      {kind === "file" ? (
        <TextField
          label={t("learning.portal.files")}
          type="file"
          multiple
          required
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
      ) : null}
      {kind === "quiz" && homework.quiz ? (
        <ol className="space-y-4">
          {homework.quiz.questions.map((q, index) => (
            <li key={q.id}>
              <fieldset className="space-y-1">
                <legend className="font-medium">
                  {index + 1}. {q.prompt}
                </legend>
                {q.kind === "short" ? (
                  <TextField
                    label={t("learning.portal.answer")}
                    value={(answers[q.id] as string | undefined) ?? ""}
                    onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}
                  />
                ) : (
                  q.choices.map((c) => {
                    const chosen = answers[q.id];
                    const checked = Array.isArray(chosen)
                      ? chosen.includes(c.id ?? "")
                      : chosen === c.id;
                    return (
                      <label key={c.id} className="flex items-center gap-2 text-sm">
                        <input
                          type={q.kind === "single" ? "radio" : "checkbox"}
                          name={q.id}
                          className="size-5"
                          checked={checked}
                          onChange={(e) => {
                            const id = c.id ?? "";
                            if (q.kind === "single") {
                              setAnswers({ ...answers, [q.id]: id });
                              return;
                            }
                            const list = Array.isArray(chosen) ? chosen : [];
                            setAnswers({
                              ...answers,
                              [q.id]: e.target.checked
                                ? [...list, id]
                                : list.filter((x) => x !== id),
                            });
                          }}
                        />
                        {c.text}
                      </label>
                    );
                  })
                )}
              </fieldset>
            </li>
          ))}
        </ol>
      ) : null}
      {submit.error ? <Alert tone="danger">{submit.error.message}</Alert> : null}
      <Button type="submit" disabled={submit.isPending}>
        {kind === "none" ? t("learning.portal.markDone") : t("learning.portal.handIn")}
      </Button>
    </form>
  );
}

function OpenResource({ id, title }: { id: string; title: string }) {
  const open = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/portal/learning/resources/{resource_id}/open", {
          params: { path: { resource_id: id } },
        }),
      ),
    onSuccess: (body) => window.open(body.url, "_blank", "noopener"),
  });
  return (
    <button type="button" className="text-left underline" onClick={() => open.mutate()}>
      {title}
    </button>
  );
}

function Resources() {
  const { t, i18n } = useTranslation();
  const resources = useQuery({
    queryKey: ["portal", "learning", "resources"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/learning/resources")),
  });
  if (resources.isPending) return <Spinner label={t("grid.loading")} />;
  if (!resources.data?.length) return <Muted>{t("learning.portal.noResources")}</Muted>;
  return (
    <ul className="space-y-2">
      {resources.data.map((r) => (
        <li key={r.id} className="rounded-lg border border-border p-3">
          <OpenResource id={r.id} title={r.title} />
          <p className="text-sm text-muted-foreground">
            {t(`learning.resources.media.${r.media_type}`)} ·{" "}
            {formatDate(r.shared_at, i18n.language)}
          </p>
          {r.message ? <p className="text-sm">{r.message}</p> : null}
          {r.description ? <p className="text-sm">{r.description}</p> : null}
        </li>
      ))}
    </ul>
  );
}

function Goals() {
  const { t } = useTranslation();
  const goals = useQuery({
    queryKey: ["portal", "learning", "goals"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/learning/goals")),
  });
  if (goals.isPending) return <Spinner label={t("grid.loading")} />;
  if (!goals.data?.length) return <Muted>{t("learning.portal.noGoals")}</Muted>;
  return (
    <ul className="space-y-3">
      {goals.data.map((g) => (
        <li key={g.id} className="space-y-1 rounded-lg border border-border p-3">
          <p className="font-medium">
            {g.title} · {g.student_name}
          </p>
          <p className="text-sm">{t(`learning.goals.statuses.${g.status}`)}</p>
          <div
            role="progressbar"
            aria-label={t("learning.goals.progress")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={g.progress_percent ?? 0}
            className="h-2 w-full max-w-sm rounded bg-muted"
          >
            <div
              className="h-2 rounded bg-brand"
              style={{ width: `${g.progress_percent ?? 0}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground">{g.progress_percent ?? 0}%</p>
          {g.milestones?.length ? (
            <ul className="text-sm">
              {g.milestones.map((m) => (
                <li key={m.id}>
                  {m.done ? "✓ " : "○ "}
                  {m.title}
                  <span className="sr-only">
                    {m.done ? t("learning.portal.done") : t("learning.portal.notYet")}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function Results() {
  const { t, i18n } = useTranslation();
  const results = useQuery({
    queryKey: ["portal", "learning", "results"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/learning/results")),
  });
  if (results.isPending) return <Spinner label={t("grid.loading")} />;
  const rows = results.data ?? [];
  const students = [...new Map(rows.map((r) => [r.student, r.student_name])).entries()];
  return (
    <div className="space-y-6">
      {!rows.length ? <Muted>{t("learning.portal.noResults")}</Muted> : null}
      {students.map(([id, name]) => (
        <TrendChart
          key={id}
          points={rows
            .filter((r) => r.student === id && r.percent !== null)
            .map((r) => ({
              date: r.date,
              percent: r.percent ?? "0",
              name: r.name,
              grade: r.grade,
            }))}
          formatDate={(iso) => formatDate(iso, i18n.language)}
          labels={{
            title: t("learning.portal.trendFor", { name }),
            date: t("learning.assessments.date"),
            assessment: t("learning.assessments.name"),
            score: t("learning.assessments.score"),
            showTable: t("learning.trend.table"),
            empty: t("learning.trend.empty"),
          }}
        />
      ))}
    </div>
  );
}

function Progress() {
  const { t, i18n } = useTranslation();
  const reports = useQuery({
    queryKey: ["portal", "learning", "progress"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/learning/progress-reports")),
  });
  if (reports.isPending) return <Spinner label={t("grid.loading")} />;
  if (!reports.data?.length) return <Muted>{t("learning.portal.noReports")}</Muted>;
  return (
    <ul className="space-y-3">
      {reports.data.map((r) => (
        <li key={r.id} className="space-y-1 rounded-lg border border-border p-3">
          <p className="font-medium">{r.title}</p>
          <p className="text-sm text-muted-foreground">
            {formatDate(r.period_start, i18n.language)} – {formatDate(r.period_end, i18n.language)}
          </p>
          <p className="whitespace-pre-wrap text-sm">{r.summary}</p>
          <a
            className="text-sm underline"
            href={`/api/v1/portal/learning/progress-reports/${r.id}/pdf`}
            target="_blank"
            rel="noreferrer"
          >
            {t("learning.progress.pdf")}
          </a>
        </li>
      ))}
    </ul>
  );
}

function Loans() {
  const { t, i18n } = useTranslation();
  const loans = useQuery({
    queryKey: ["portal", "learning", "loans"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/learning/loans")),
  });
  if (loans.isPending) return <Spinner label={t("grid.loading")} />;
  if (!loans.data?.length) return <Muted>{t("learning.portal.noLoans")}</Muted>;
  return (
    <ul className="space-y-2">
      {loans.data.map((l) => (
        <li key={l.id} className="rounded-lg border border-border p-3 text-sm">
          <p className="font-medium">
            {l.item} · {l.student_name}
          </p>
          <p>
            {l.status === "out"
              ? t("learning.portal.dueBack", { date: formatDate(l.due_date, i18n.language) })
              : t(`learning.portal.loanStatus.${l.status}`)}
            {l.is_overdue ? ` · ${t("learning.portal.overdue")}` : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}
