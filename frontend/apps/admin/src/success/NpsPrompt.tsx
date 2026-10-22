import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api } from "../api";
import { track } from "./analytics";
import { GUIDANCE_KEY } from "./guidance";

/**
 * The in-app NPS survey (E30 FR-30-6). A non-modal region in the corner: it never takes
 * focus or blocks the page. "Not now" rests it for 30 days, an answer for 90.
 */
export function NpsPrompt({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const titleId = useId();
  const commentId = useId();
  const [score, setScore] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [thanked, setThanked] = useState(false);
  const answer = useMutation({
    mutationFn: async (value: number | null) =>
      unwrap(
        await api.POST("/api/v1/surveys/responses", {
          body: { kind: "nps", score: value, comment: value === null ? "" : comment },
        }),
      ),
    onSuccess: (_data, value) => {
      track(value === null ? "nps.dismissed" : "nps.answered");
      if (value === null) onClose();
      else setThanked(true);
      void queryClient.invalidateQueries({ queryKey: GUIDANCE_KEY });
    },
  });
  if (thanked) {
    return (
      <section
        aria-labelledby={titleId}
        className="fixed bottom-4 left-4 z-40 w-[min(380px,calc(100vw-2rem))] rounded-xl border border-border bg-surface px-5 py-4 text-foreground shadow-[0_8px_24px_-8px_rgb(15_23_42/0.25)]"
      >
        <h2 id={titleId} className="text-base font-semibold" role="status">
          {t("nps.thanks")}
        </h2>
        <Button size="sm" variant="ghost" className="mt-2 -ml-3" onClick={onClose}>
          {t("nps.close")}
        </Button>
      </section>
    );
  }
  return (
    <section
      aria-labelledby={titleId}
      className="fixed bottom-4 left-4 z-40 w-[min(380px,calc(100vw-2rem))] rounded-xl border border-border bg-surface px-5 py-4 text-foreground shadow-[0_8px_24px_-8px_rgb(15_23_42/0.25)]"
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (score !== null) answer.mutate(score);
        }}
        className="space-y-3"
      >
        <fieldset>
          <legend id={titleId} className="text-base font-semibold">
            {t("nps.question")}
          </legend>
          <div className="mt-2 grid grid-cols-11 gap-1">
            {Array.from({ length: 11 }, (_, n) => (
              <label key={n} className="min-w-0 cursor-pointer">
                <input
                  type="radio"
                  name="nps-score"
                  value={n}
                  checked={score === n}
                  onChange={() => setScore(n)}
                  className="peer sr-only"
                />
                <span className="grid h-8 w-full place-items-center rounded-md border border-field bg-surface text-sm tabular-nums hover:bg-muted peer-checked:border-foreground peer-checked:bg-muted peer-checked:font-semibold peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-link">
                  {n}
                </span>
              </label>
            ))}
          </div>
          <p className="mt-1 flex justify-between text-xs text-muted-foreground">
            <span>{t("nps.low")}</span>
            <span>{t("nps.high")}</span>
          </p>
        </fieldset>
        {score !== null ? (
          <div className="space-y-1">
            <label htmlFor={commentId} className="text-sm font-medium">
              {t("nps.comment")}
            </label>
            <textarea
              id={commentId}
              rows={2}
              maxLength={2000}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              className="w-full rounded-md border border-field bg-surface px-3 py-2 text-sm"
            />
          </div>
        ) : null}
        <div className="flex gap-2">
          <Button type="submit" size="sm" disabled={score === null} loading={answer.isPending}>
            {t("nps.send")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            disabled={answer.isPending}
            onClick={() => answer.mutate(null)}
          >
            {t("nps.notNow")}
          </Button>
        </div>
      </form>
    </section>
  );
}
