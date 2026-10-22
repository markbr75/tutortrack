import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, PageHeader, RuledPanel, TextAreaField } from "@tutortrack/ui";
import { useMutation } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import { api, usePermission } from "../api";
import { useAiFeature } from "./ai";
import { AiError, AiFeedback, AiNotice } from "./AiParts";

type Answer = components["schemas"]["AICopilot"];
interface Turn {
  question: string;
  answer: Answer;
}

/** The business copilot (FR-31-7): questions answered from the standard reports the person
 * may run, each answer citing the reports and filters used, with links to open them. */
export function CopilotPage() {
  const { t, i18n } = useTranslation();
  const enabled = useAiFeature("copilot");
  const allowed = usePermission("ai.copilot");
  const questionId = useId();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const ask = useMutation({
    mutationFn: async (q: string) =>
      unwrap(
        await api.POST("/api/v1/ai/copilot", {
          body: {
            question: q,
            history: turns.map((turn) => ({ question: turn.question, answer: turn.answer.answer })),
          },
        }),
      ),
    onSuccess: (answer, q) => {
      setTurns((all) => [...all, { question: q, answer }]);
      setQuestion("");
    },
  });
  if (!allowed || !enabled) {
    return (
      <div className="max-w-3xl">
        <PageHeader title={t("ai.copilot.title")} />
        <Alert>{t("ai.copilot.unavailable")}</Alert>
      </div>
    );
  }
  return (
    <div className="max-w-3xl">
      <PageHeader title={t("ai.copilot.title")} description={t("ai.copilot.intro")} />
      <div className="space-y-6">
        <ol
          role="log"
          aria-live="polite"
          aria-label={t("ai.copilot.conversation")}
          className="space-y-6 empty:hidden"
        >
          {turns.map((turn, i) => (
            <li key={i}>
              <RuledPanel
                flush
                label={turn.question}
                footer={<AiFeedback request={turn.answer.request} />}
              >
                <p className="border-b border-border px-5 py-3.5 font-medium">{turn.question}</p>
                <div className="space-y-3 px-5 py-4 text-sm">
                  <p className="whitespace-pre-wrap">{turn.answer.answer}</p>
                  {turn.answer.citations.length ? (
                    <div>
                      <h2 className="text-xs font-semibold text-muted-foreground">
                        {t("ai.copilot.sources")}
                      </h2>
                      <ul className="mt-1 space-y-0.5 text-xs">
                        {turn.answer.citations.map((c) => (
                          <li key={c.index}>
                            <span className="text-muted-foreground tabular-nums">[{c.index}]</span>{" "}
                            <a
                              href={c.link}
                              className="font-medium text-link underline-offset-2 hover:underline"
                            >
                              {t("ai.copilot.openReport", { title: c.title })}
                            </a>{" "}
                            <span className="text-muted-foreground tabular-nums">
                              {[c.period.from, c.period.to]
                                .map((d) => (d ? formatDate(d, i18n.language) : ""))
                                .join(" – ")}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              </RuledPanel>
            </li>
          ))}
        </ol>
        <form
          aria-labelledby={`${questionId}-title`}
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            if (question.trim()) ask.mutate(question.trim());
          }}
        >
          <RuledPanel
            flush
            titleId={`${questionId}-title`}
            title={t("designS9b.ai.askTitle")}
            footer={
              <>
                <Button type="submit" loading={ask.isPending} disabled={!question.trim()}>
                  {t("ai.copilot.ask")}
                </Button>
                {ask.isPending ? (
                  <p role="status" className="text-muted-foreground">
                    {t("ai.copilot.thinking")}
                  </p>
                ) : null}
              </>
            }
          >
            <div className="space-y-3 px-5 py-4">
              <TextAreaField
                id={questionId}
                label={t("ai.copilot.label")}
                rows={2}
                value={question}
                placeholder={t("ai.copilot.placeholder")}
                onChange={(e) => setQuestion(e.target.value)}
              />
              <AiError error={ask.error} />
            </div>
          </RuledPanel>
        </form>
        <AiNotice />
      </div>
    </div>
  );
}
