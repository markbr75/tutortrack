import { unwrap } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { PanelEmpty, PanelLoading, PortalHeader, Word } from "../layout/PortalPage";

type Answer = string | string[];

/** Online subject tests for the subjects the tutor teaches (FR-18-3, gap batch G5a): take a
 * test, see the score; passing marks the subject as assessed for staff to approve. */
export function SubjectTestsPage() {
  const { t, i18n } = useTranslation();
  const [taking, setTaking] = useState<string | null>(null);
  const tests = useQuery({
    queryKey: ["tutor", "subject-tests"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/subject-tests")),
  });
  if (taking) return <TakeTest quizId={taking} onDone={() => setTaking(null)} />;
  return (
    <div>
      <PortalHeader title={t("hiring.tests.title")} description={t("hiring.tests.intro")} />
      <RuledPanel label={t("hiring.tests.title")} flush>
        {tests.isPending ? (
          <PanelLoading label={t("grid.loading")} />
        ) : !tests.data?.length ? (
          <PanelEmpty>{t("hiring.tests.none")}</PanelEmpty>
        ) : (
          <PanelRows>
            {tests.data.map((test) => (
              <PanelRow
                key={test.id}
                className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2"
              >
                <span className="min-w-0">
                  <span className="block font-medium">{test.title}</span>
                  <span className="block text-xs text-muted-foreground tabular-nums">
                    {test.subjects.join(", ")} ·{" "}
                    {t("hiring.tests.questionsCount", { count: test.question_count })} ·{" "}
                    {t("hiring.tests.passMarkValue", { percent: test.pass_percent })}
                    {test.time_limit_minutes
                      ? ` · ${t("hiring.tests.timeLimit", { minutes: test.time_limit_minutes })}`
                      : ""}
                  </span>
                  {test.status !== "not_taken" ? (
                    <span className="block text-xs tabular-nums">
                      <Word className="font-medium">
                        {test.status === "passed"
                          ? t("hiring.tests.passed")
                          : t("hiring.tests.failed")}
                      </Word>
                      {test.percent != null
                        ? ` · ${t("hiring.tests.score", { percent: Math.round(Number(test.percent)) })}`
                        : ""}
                      {test.status === "failed" && test.retake_at && !test.can_take
                        ? ` · ${t("hiring.tests.retakeFrom", {
                            date: formatDate(test.retake_at, i18n.language),
                          })}`
                        : ""}
                    </span>
                  ) : null}
                </span>
                {test.can_take ? (
                  <Button
                    size="sm"
                    variant={test.status === "failed" ? "secondary" : "primary"}
                    onClick={() => setTaking(test.id)}
                  >
                    {test.status === "failed"
                      ? t("hiring.tests.retake", { title: test.title })
                      : t("hiring.tests.start", { title: test.title })}
                  </Button>
                ) : null}
              </PanelRow>
            ))}
          </PanelRows>
        )}
      </RuledPanel>
    </div>
  );
}

function TakeTest({ quizId, onDone }: { quizId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const test = useQuery({
    queryKey: ["tutor", "subject-test", quizId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/me/subject-tests/{quiz_id}", {
          params: { path: { quiz_id: quizId } },
        }),
      ),
  });
  const submit = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/me/subject-tests/{quiz_id}", {
          params: { path: { quiz_id: quizId } },
          body: { answers: answers as Record<string, never> },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["tutor", "subject-tests"] }),
  });
  if (!test.data) return <Spinner label={t("grid.loading")} />;
  if (submit.data) {
    const r = submit.data;
    return (
      <div>
        <PortalHeader title={test.data.title} />
        <div className="space-y-4">
          <Alert tone={r.passed ? "success" : "warning"}>
            {r.passed
              ? t("hiring.tests.resultPassed", { percent: Math.round(Number(r.percent)) })
              : t("hiring.tests.resultFailed", {
                  percent: Math.round(Number(r.percent)),
                  pass: r.pass_percent,
                })}
          </Alert>
          {r.assessed.length ? (
            <p className="text-sm">
              {t("hiring.tests.assessed", { subjects: r.assessed.join(", ") })}
            </p>
          ) : null}
          <Button variant="secondary" onClick={onDone}>
            {t("hiring.tests.back")}
          </Button>
        </div>
      </div>
    );
  }
  const set = (id: string, value: Answer) => setAnswers({ ...answers, [id]: value });
  return (
    <div>
      <PortalHeader title={test.data.title} description={test.data.description || undefined} />
      <form
        aria-label={test.data.title}
        onSubmit={(e) => {
          e.preventDefault();
          submit.mutate();
        }}
      >
        <RuledPanel label={test.data.title} flush>
          <ol className="divide-y divide-rule">
            {test.data.questions.map((q, i) => (
              <li key={q.id} className="px-5 py-4">
                <fieldset className="space-y-2 text-sm">
                  <legend className="mb-1 font-medium">
                    {t("hiring.tests.questionN", { n: i + 1 })}: {q.prompt}
                  </legend>
                  {q.kind === "short" ? (
                    <TextField
                      label={t("hiring.tests.yourAnswer")}
                      value={(answers[q.id] as string) ?? ""}
                      onChange={(e) => set(q.id, e.target.value)}
                    />
                  ) : (
                    (q.choices as { id: string; text: string }[]).map((c) => {
                      const chosen = answers[q.id];
                      const checked =
                        q.kind === "multiple"
                          ? Array.isArray(chosen) && chosen.includes(c.id)
                          : chosen === c.id;
                      return (
                        <label key={c.id} className="flex min-h-8 items-center gap-2">
                          <input
                            type={q.kind === "multiple" ? "checkbox" : "radio"}
                            name={q.id}
                            className="size-4"
                            checked={checked}
                            onChange={(e) => {
                              if (q.kind !== "multiple") return set(q.id, c.id);
                              const list = Array.isArray(chosen) ? chosen : [];
                              set(
                                q.id,
                                e.target.checked
                                  ? [...list, c.id]
                                  : list.filter((x) => x !== c.id),
                              );
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
          {submit.error ? (
            <div className="px-5 pb-4">
              <Alert tone="danger">{submit.error.message}</Alert>
            </div>
          ) : null}
          <PanelFooter>
            <Button type="submit" loading={submit.isPending}>
              {t("hiring.tests.submit")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="text-muted-foreground hover:text-foreground"
              onClick={onDone}
            >
              {t("common.cancel")}
            </Button>
          </PanelFooter>
        </RuledPanel>
      </form>
    </div>
  );
}
