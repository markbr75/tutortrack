import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FactList,
  PanelFooter,
  PanelRow,
  PanelRows,
  RegisterMark,
  RuledPanel,
  Spinner,
  Tabs,
  TextAreaField,
  TextField,
  TrendChart,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";
import { useState, type ReactNode } from "react";

import { api, uploadFile } from "../api";
import { FileField, PanelEmpty, PanelLoading, PortalHeader, Word } from "../layout/PortalPage";

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
    <div>
      <PortalHeader title={t("learning.portal.title")} />
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

/** One flush ruled panel named for its tab: skeleton rows, one sentence when empty, or rows. */
function TabPanel({
  label,
  loading,
  empty,
  children,
}: {
  label: string;
  loading: boolean;
  empty?: string | false;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <RuledPanel label={label} flush>
      {loading ? (
        <PanelLoading label={t("grid.loading")} />
      ) : empty ? (
        <PanelEmpty>{empty}</PanelEmpty>
      ) : (
        children
      )}
    </RuledPanel>
  );
}

function HomeworkList() {
  const { t, i18n } = useTranslation();
  const homework = useQuery({
    queryKey: ["portal", "learning", "homework"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/learning/homework")),
  });
  return (
    <TabPanel
      label={t("learning.portal.tabs.homework")}
      loading={homework.isPending}
      empty={!homework.data?.length && t("learning.portal.noHomework")}
    >
      <PanelRows>
        {homework.data?.map((h) => (
          <PanelRow key={h.id} className="flex flex-wrap items-baseline justify-between gap-x-4">
            <div className="min-w-0">
              <Link
                to="/learning/homework/$assignmentId"
                params={{ assignmentId: h.id }}
                className="font-medium underline-offset-2 hover:text-link hover:underline"
              >
                {h.title}
              </Link>
              <p className="text-xs text-muted-foreground tabular-nums">
                {h.student_name} ·{" "}
                {t("learning.portal.due", { when: formatDateTime(h.due_at, i18n.language) })}
              </p>
            </div>
            <p className="text-sm">
              {h.overdue ? (
                <Word tone="margin">{t("learning.portal.overdue")}</Word>
              ) : (
                t(`learning.portal.status.${h.status}`)
              )}
              {h.grade ? ` · ${h.grade}` : ""}
            </p>
          </PanelRow>
        ))}
      </PanelRows>
    </TabPanel>
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
  if (!h) return <Alert tone="danger">{t("errors.generic")}</Alert>;
  return (
    <article aria-label={h.title}>
      <PortalHeader
        back={<Link to="/learning">{t("learning.portal.title")}</Link>}
        title={h.title}
        description={
          <>
            <span className="tabular-nums">
              {[
                h.student_name,
                h.tutor_name,
                t("learning.portal.due", { when: formatDateTime(h.due_at, i18n.language) }),
                h.expected_minutes ? t("learning.portal.minutes", { n: h.expected_minutes }) : "",
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
            {" · "}
            {h.overdue ? (
              <Word tone="margin">{t("learning.portal.overdue")}</Word>
            ) : (
              <Word className="text-foreground">{t(`learning.portal.status.${h.status}`)}</Word>
            )}
          </>
        }
      />
      <div className="space-y-6">
        {h.instructions ? (
          <RuledPanel label={t("designS10.instructions")}>
            <p className="text-sm whitespace-pre-wrap">{h.instructions}</p>
          </RuledPanel>
        ) : null}
        {h.resources.length ? (
          <RuledPanel title={t("learning.portal.resources")} flush>
            <PanelRows>
              {h.resources.map((r) => (
                <PanelRow key={r.id}>
                  <OpenResource id={r.id} title={r.title} />
                </PanelRow>
              ))}
            </PanelRows>
          </RuledPanel>
        ) : null}
        {h.grade || h.feedback ? (
          <RuledPanel title={t("learning.portal.feedback")} flush>
            {h.grade ? <FactList items={[[t("learning.homework.grade"), h.grade]]} /> : null}
            {h.feedback ? (
              <p
                className={
                  h.grade
                    ? "border-t border-rule px-5 py-2.5 text-sm whitespace-pre-wrap"
                    : "px-5 py-2.5 text-sm whitespace-pre-wrap"
                }
              >
                {h.feedback}
              </p>
            ) : null}
          </RuledPanel>
        ) : null}
        {h.quiz_result ? (
          <Alert tone={h.quiz_result.passed ? "success" : "info"}>
            {t(h.quiz_result.passed ? "learning.portal.quizPassed" : "learning.portal.quizScore", {
              percent: h.quiz_result.percent,
            })}
          </Alert>
        ) : null}
        {h.submissions.length ? (
          <RuledPanel title={t("learning.portal.handedIn")} flush>
            <PanelRows>
              {h.submissions.map((s) => (
                <PanelRow key={s.id}>
                  <p className="text-xs text-muted-foreground tabular-nums">
                    {formatDateTime(s.created_at, i18n.language)}
                    {s.is_late ? ` · ${t("learning.portal.late")}` : ""}
                  </p>
                  {s.body ? <p className="line-clamp-3 whitespace-pre-wrap">{s.body}</p> : null}
                  {s.files.length ? (
                    <p className="text-xs">{s.files.map((f) => f.filename).join(" · ")}</p>
                  ) : null}
                </PanelRow>
              ))}
            </PanelRows>
          </RuledPanel>
        ) : null}
        {h.can_submit ? <SubmitForm homework={h} /> : null}
      </div>
    </article>
  );
}

function SubmitForm({ homework }: { homework: Homework }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
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
      aria-label={t("learning.portal.handIn")}
      onSubmit={(e) => {
        e.preventDefault();
        submit.mutate();
      }}
    >
      <RuledPanel title={t("learning.portal.handIn")} flush>
        <div className="space-y-4 px-5 py-4">
          {kind === "text" ? (
            <TextAreaField
              label={t("learning.portal.answer")}
              required
              rows={6}
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
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
            <FileField
              label={t("learning.portal.files")}
              multiple
              required
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            />
          ) : null}
          {kind === "quiz" && homework.quiz ? (
            <ol className="space-y-5">
              {homework.quiz.questions.map((q, index) => (
                <li key={q.id}>
                  <fieldset className="space-y-2">
                    <legend className="text-sm font-medium">
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
                          <label key={c.id} className="flex min-h-8 items-center gap-2 text-sm">
                            <input
                              type={q.kind === "single" ? "radio" : "checkbox"}
                              name={q.id}
                              className="size-4"
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
        </div>
        <PanelFooter>
          <Button type="submit" disabled={submit.isPending}>
            {kind === "none" ? t("learning.portal.markDone") : t("learning.portal.handIn")}
          </Button>
        </PanelFooter>
      </RuledPanel>
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
    <button
      type="button"
      className="text-left font-medium text-link underline-offset-2 hover:underline"
      onClick={() => open.mutate()}
    >
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
  return (
    <TabPanel
      label={t("learning.portal.tabs.resources")}
      loading={resources.isPending}
      empty={!resources.data?.length && t("learning.portal.noResources")}
    >
      <PanelRows>
        {resources.data?.map((r) => (
          <PanelRow key={r.id} className="space-y-0.5">
            <OpenResource id={r.id} title={r.title} />
            <p className="text-xs text-muted-foreground tabular-nums">
              {t(`learning.resources.media.${r.media_type}`)} ·{" "}
              {formatDate(r.shared_at, i18n.language)}
            </p>
            {r.message ? <p>{r.message}</p> : null}
            {r.description ? <p className="text-muted-foreground">{r.description}</p> : null}
          </PanelRow>
        ))}
      </PanelRows>
    </TabPanel>
  );
}

/** Goals as ruled rows: progress in words, never a bar; milestones as drawn marks. */
function Goals() {
  const { t } = useTranslation();
  const goals = useQuery({
    queryKey: ["portal", "learning", "goals"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/learning/goals")),
  });
  return (
    <TabPanel
      label={t("learning.portal.tabs.goals")}
      loading={goals.isPending}
      empty={!goals.data?.length && t("learning.portal.noGoals")}
    >
      <PanelRows>
        {goals.data?.map((g) => {
          const milestones = g.milestones ?? [];
          const done = milestones.filter((m) => m.done).length;
          return (
            <PanelRow key={g.id} className="space-y-2">
              <div>
                <p className="font-medium">
                  {g.title} · {g.student_name}
                </p>
                <p className="text-xs text-muted-foreground tabular-nums">
                  {[
                    t(`learning.goals.statuses.${g.status}`),
                    t("designS6.learning.progressDone", { percent: g.progress_percent ?? 0 }),
                    milestones.length
                      ? t("designS6.learning.milestonesDone", { done, total: milestones.length })
                      : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              {milestones.length ? (
                <ul className="space-y-1">
                  {milestones.map((m) => (
                    <li key={m.id} className="flex items-start gap-2">
                      {m.done ? (
                        <Check
                          aria-hidden="true"
                          className="mt-0.5 size-4 shrink-0"
                          strokeWidth={2.2}
                        />
                      ) : (
                        // Still to come: the register's pale dashed ring, never the solid
                        // "missed" ring. The words after the title say it for screen readers.
                        <span aria-hidden="true" className="mt-0.5 shrink-0">
                          <RegisterMark kind="upcoming" label="" className="size-4" />
                        </span>
                      )}
                      <span className={m.done ? "" : "text-muted-foreground"}>
                        {m.title}
                        <span className="sr-only">
                          {" "}
                          ({m.done ? t("learning.portal.done") : t("learning.portal.notYet")})
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </PanelRow>
          );
        })}
      </PanelRows>
    </TabPanel>
  );
}

function Results() {
  const { t, i18n } = useTranslation();
  const results = useQuery({
    queryKey: ["portal", "learning", "results"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/learning/results")),
  });
  if (results.isPending) {
    return <TabPanel label={t("learning.portal.tabs.results")} loading />;
  }
  const rows = results.data ?? [];
  const students = [...new Map(rows.map((r) => [r.student, r.student_name])).entries()];
  if (!rows.length) {
    return (
      <TabPanel
        label={t("learning.portal.tabs.results")}
        loading={false}
        empty={t("learning.portal.noResults")}
      />
    );
  }
  return (
    <div className="space-y-6">
      {students.map(([id, name]) => (
        <RuledPanel key={id} title={t("learning.portal.trendFor", { name })}>
          <TrendChart
            hideTitle
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
        </RuledPanel>
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
  return (
    <TabPanel
      label={t("learning.portal.tabs.progress")}
      loading={reports.isPending}
      empty={!reports.data?.length && t("learning.portal.noReports")}
    >
      <PanelRows>
        {reports.data?.map((r) => (
          <PanelRow key={r.id} className="space-y-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4">
              <p className="font-medium">{r.title}</p>
              <a
                className="font-medium text-link underline-offset-2 hover:underline"
                href={`/api/v1/portal/learning/progress-reports/${r.id}/pdf`}
                target="_blank"
                rel="noreferrer"
              >
                {t("learning.progress.pdf")}
                <span className="sr-only"> {r.title}</span>
              </a>
            </div>
            <p className="text-xs text-muted-foreground tabular-nums">
              {formatDate(r.period_start, i18n.language)} –{" "}
              {formatDate(r.period_end, i18n.language)}
            </p>
            <p className="whitespace-pre-wrap">{r.summary}</p>
          </PanelRow>
        ))}
      </PanelRows>
    </TabPanel>
  );
}

function Loans() {
  const { t, i18n } = useTranslation();
  const loans = useQuery({
    queryKey: ["portal", "learning", "loans"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/learning/loans")),
  });
  return (
    <TabPanel
      label={t("learning.portal.tabs.loans")}
      loading={loans.isPending}
      empty={!loans.data?.length && t("learning.portal.noLoans")}
    >
      <PanelRows>
        {loans.data?.map((l) => (
          <PanelRow key={l.id} className="flex flex-wrap items-baseline justify-between gap-x-4">
            <div className="min-w-0">
              <p className="font-medium">{l.item}</p>
              <p className="text-xs text-muted-foreground tabular-nums">
                {l.student_name} ·{" "}
                {l.status === "out"
                  ? t("learning.portal.dueBack", { date: formatDate(l.due_date, i18n.language) })
                  : t(`learning.portal.loanStatus.${l.status}`)}
              </p>
            </div>
            {l.is_overdue ? <Word tone="margin">{t("learning.portal.overdue")}</Word> : null}
          </PanelRow>
        ))}
      </PanelRows>
    </TabPanel>
  );
}
