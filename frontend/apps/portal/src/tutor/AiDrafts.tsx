import { ApiError, unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, PanelFooter, RuledPanel, TextAreaField, TextField } from "@tutortrack/ui";
import { useMutation } from "@tanstack/react-query";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import { FileField } from "../layout/PortalPage";
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

/** "Was this helpful?" with two drawn thumbs (pressed buttons, each named in words). */
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
      className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground"
    >
      <span className="mr-1">{t("ai.feedback.label")}</span>
      {(["up", "down"] as const).map((value) => {
        const Icon = value === "up" ? ThumbsUp : ThumbsDown;
        return (
          <button
            key={value}
            type="button"
            aria-pressed={rating === value}
            onClick={() => send.mutate(value)}
            className="grid size-8 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground aria-pressed:bg-muted aria-pressed:text-foreground"
          >
            <Icon aria-hidden="true" className="size-4" strokeWidth={1.75} />
            <span className="sr-only">{t(`ai.feedback.${value}`)}</span>
          </button>
        );
      })}
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
 * checks and edits them, then submits as usual. A ruled panel on the clean leaf, no tint. */
export function AiReportDrafter({
  reportId,
  onDraft,
}: {
  reportId: string;
  onDraft: (draft: ReportDraft) => void;
}) {
  const { t } = useTranslation();
  const enabled = useAiFeature("lesson_report");
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
    <RuledPanel title={t("ai.report.title")} flush>
      <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <TextAreaField
            label={t("ai.report.notes")}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
        <FileField
          label={t("ai.report.voice")}
          accept="audio/*"
          capture="user"
          onChange={(e) => setAudio(e.target.files?.[0] ?? null)}
        />
      </div>
      <div className="space-y-3 px-5 empty:hidden [&:has(>*)]:pb-4">
        <AiProblem error={draft.error} />
        {draft.data ? (
          <div
            role="status"
            className="space-y-1 rounded-md border border-border px-4 py-3 text-sm"
          >
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
      </div>
      <PanelFooter>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={!notes.trim() && !audio}
          loading={draft.isPending}
          onClick={() => draft.mutate()}
        >
          {t("ai.report.draft")}
        </Button>
      </PanelFooter>
    </RuledPanel>
  );
}

/** FR-31-8: draft a public profile bio (staff still approve it, E24). */
export function AiBioHelper({ tutorId, onUse }: { tutorId: string; onUse: (bio: string) => void }) {
  const { t } = useTranslation();
  const enabled = useAiFeature("content");
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
    <div className="space-y-2 border-t border-rule pt-3 text-sm">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-48 flex-1">
          <TextField
            size="sm"
            label={t("ai.bio.brief")}
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
          />
        </div>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          loading={write.isPending}
          onClick={() => write.mutate()}
        >
          {t("ai.bio.draft")}
        </Button>
      </div>
      <AiProblem error={write.error} />
      {write.data ? (
        <div aria-live="polite" className="space-y-2">
          <p className="rounded-md border border-border px-3 py-2 whitespace-pre-wrap">
            {write.data.body}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => onUse(write.data.body)}
            >
              {t("ai.useDraft")}
            </Button>
            <Feedback request={write.data.request} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
