import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button } from "@tutortrack/ui";
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
  const { t } = useTranslation();
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
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold">{t("ai.copilot.title")}</h1>
        <Alert>{t("ai.copilot.unavailable")}</Alert>
      </div>
    );
  }
  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">{t("ai.copilot.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("ai.copilot.intro")}</p>
      <ol
        role="log"
        aria-live="polite"
        aria-label={t("ai.copilot.conversation")}
        className="space-y-4"
      >
        {turns.map((turn, i) => (
          <li key={i} className="space-y-2">
            <p className="rounded-md bg-muted p-2 text-sm font-medium">{turn.question}</p>
            <div className="space-y-2 rounded-md border border-border p-3 text-sm">
              <p className="whitespace-pre-wrap">{turn.answer.answer}</p>
              {turn.answer.citations.length ? (
                <div>
                  <h2 className="text-xs font-semibold">{t("ai.copilot.sources")}</h2>
                  <ul className="text-xs">
                    {turn.answer.citations.map((c) => (
                      <li key={c.index}>
                        [{c.index}]{" "}
                        <a href={c.link} className="underline">
                          {t("ai.copilot.openReport", { title: c.title })}
                        </a>{" "}
                        <span className="text-muted-foreground">
                          {c.period.from} – {c.period.to}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <AiFeedback request={turn.answer.request} />
            </div>
          </li>
        ))}
      </ol>
      {ask.isPending ? <p className="text-sm">{t("ai.copilot.thinking")}</p> : null}
      <AiError error={ask.error} />
      <form
        className="space-y-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (question.trim()) ask.mutate(question.trim());
        }}
      >
        <label htmlFor={questionId} className="text-sm font-medium">
          {t("ai.copilot.label")}
        </label>
        <textarea
          id={questionId}
          rows={2}
          value={question}
          placeholder={t("ai.copilot.placeholder")}
          onChange={(e) => setQuestion(e.target.value)}
          className="w-full rounded-md border border-border bg-background p-2 text-sm"
        />
        <Button type="submit" loading={ask.isPending} disabled={!question.trim()}>
          {t("ai.copilot.ask")}
        </Button>
      </form>
      <AiNotice />
    </div>
  );
}
