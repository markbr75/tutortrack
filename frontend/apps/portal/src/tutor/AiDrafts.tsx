import { ApiError, unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button } from "@tutortrack/ui";
import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api } from "../api";
import { useAiFeature } from "./aiApi";

const ERRORS: Record<string, string> = {
  "ai-credits-exhausted": "ai.errors.credits",
  "ai-rate-limited": "ai.errors.rate",
  "ai-refused": "ai.errors.refused",
  "ai-unavailable": "ai.errors.unavailable",
  "ai-incomplete": "ai.errors.incomplete",
  "feature-disabled": "ai.errors.disabled",
};

function AiProblem({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  const key = error instanceof ApiError ? ERRORS[error.code] : undefined;
  return <Alert tone="danger">{key ? t(key) : (error as Error).message}</Alert>;
}

function Feedback({ request }: { request: string }) {
  const { t } = useTranslation();
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const send = useMutation({
    mutationFn: async (value: "up" | "down") =>
      unwrap(
        await api.POST("/api/v1/ai/feedback", { body: { request, rating: value, comment: "" } }),
      ),
    onSuccess: (_d, value) => setRating(value),
  });
  return (
    <div
      role="group"
      aria-label={t("ai.feedback.label")}
      className="flex items-center gap-1 text-xs"
    >
      <span>{t("ai.feedback.label")}</span>
      {(["up", "down"] as const).map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={rating === value}
          onClick={() => send.mutate(value)}
          className="rounded-md border border-border px-2 py-0.5 aria-pressed:bg-muted"
        >
          <span aria-hidden="true">{value === "up" ? "👍" : "👎"}</span>
          <span className="sr-only">{t(`ai.feedback.${value}`)}</span>
        </button>
      ))}
      {rating ? <span role="status">{t("ai.feedback.thanks")}</span> : null}
    </div>
  );
}

export interface ReportDraft {
  request: string;
  answers: Record<string, unknown>;
  homework: string;
  suggested_topics: { id: string; name: string }[];
}

/** FR-31-1: rough notes or a voice note become a draft of the report's answers. The tutor
 * checks and edits them, then submits as usual. */
export function AiReportDrafter({
  reportId,
  onDraft,
}: {
  reportId: string;
  onDraft: (draft: ReportDraft) => void;
}) {
  const { t } = useTranslation();
  const enabled = useAiFeature("lesson_report");
  const notesId = useId();
  const audioId = useId();
  const [notes, setNotes] = useState("");
  const [audio, setAudio] = useState<File | null>(null);
  const draft = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.append("notes", notes);
      if (audio) form.append("audio", audio);
      return unwrap(
        await api.POST("/api/v1/ai/lesson-reports/{report_id}/draft", {
          params: { path: { report_id: reportId } },
          body: form as never,
          bodySerializer: (body: unknown) => body as FormData,
        }),
      );
    },
    onSuccess: (body) => onDraft(body),
  });
  if (!enabled) return null;
  return (
    <section
      aria-labelledby={`${notesId}-h`}
      className="space-y-2 rounded-md border border-violet-200 p-3"
    >
      <h2 id={`${notesId}-h`} className="font-semibold">
        {t("ai.report.title")}
      </h2>
      <label htmlFor={notesId} className="text-sm font-medium">
        {t("ai.report.notes")}
      </label>
      <textarea
        id={notesId}
        rows={3}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        className="w-full rounded-md border border-border bg-background p-2 text-sm"
      />
      <label htmlFor={audioId} className="block text-sm font-medium">
        {t("ai.report.voice")}
      </label>
      <input
        id={audioId}
        type="file"
        accept="audio/*"
        capture="user"
        className="text-sm"
        onChange={(e) => setAudio(e.target.files?.[0] ?? null)}
      />
      <div>
        <Button
          type="button"
          size="sm"
          disabled={!notes.trim() && !audio}
          loading={draft.isPending}
          onClick={() => draft.mutate()}
        >
          {t("ai.report.draft")}
        </Button>
      </div>
      <AiProblem error={draft.error} />
      {draft.data ? (
        <div role="status" className="space-y-1 text-sm">
          <p>{t("ai.report.drafted")}</p>
          {draft.data.suggested_topics.length ? (
            <p>
              {t("ai.report.topics", {
                topics: draft.data.suggested_topics.map((tp) => tp.name).join(", "),
              })}
            </p>
          ) : null}
          {draft.data.homework ? (
            <p>{t("ai.report.homework", { homework: draft.data.homework })}</p>
          ) : null}
          <p className="text-xs text-muted-foreground">{t("ai.disclaimer")}</p>
          <Feedback request={draft.data.request} />
        </div>
      ) : null}
    </section>
  );
}

/** FR-31-8: draft a public profile bio (staff still approve it, E24). */
export function AiBioHelper({ tutorId, onUse }: { tutorId: string; onUse: (bio: string) => void }) {
  const { t } = useTranslation();
  const enabled = useAiFeature("content");
  const briefId = useId();
  const [brief, setBrief] = useState("");
  const write = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/ai/content", {
          body: { kind: "bio", brief, tutor: tutorId, channel: "email", title: "", location: "" },
        }),
      ),
  });
  if (!enabled) return null;
  return (
    <div className="space-y-2 rounded-md border border-violet-200 p-2 text-sm">
      <label htmlFor={briefId} className="font-medium">
        {t("ai.bio.brief")}
      </label>
      <input
        id={briefId}
        value={brief}
        onChange={(e) => setBrief(e.target.value)}
        className="w-full rounded-md border border-border bg-background px-3 py-2"
      />
      <Button
        type="button"
        size="sm"
        variant="secondary"
        loading={write.isPending}
        onClick={() => write.mutate()}
      >
        {t("ai.bio.draft")}
      </Button>
      <AiProblem error={write.error} />
      {write.data ? (
        <div aria-live="polite" className="space-y-1">
          <p className="whitespace-pre-wrap rounded-md bg-muted p-2">{write.data.body}</p>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" onClick={() => onUse(write.data.body)}>
              {t("ai.useDraft")}
            </Button>
            <Feedback request={write.data.request} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
