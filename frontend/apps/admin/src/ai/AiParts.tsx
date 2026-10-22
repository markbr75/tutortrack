import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";
import { useId, useState } from "react";

import { api, usePermission } from "../api";
import { aiError, useAiFeature, type AiProposal } from "./ai";

/** Thumbs up/down on an AI response; with the draft and the final text the server keeps
 * only edit statistics (FR-31 §4 feedback capture). */
export function AiFeedback({
  request,
  draftText,
  finalText,
}: {
  request: string;
  draftText?: string;
  finalText?: string;
}) {
  const { t } = useTranslation();
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const send = useMutation({
    mutationFn: async (value: "up" | "down") =>
      unwrap(
        await api.POST("/api/v1/ai/feedback", {
          body: {
            request,
            rating: value,
            comment: "",
            ...(draftText !== undefined && finalText !== undefined
              ? { draft_text: draftText, final_text: finalText }
              : {}),
          },
        }),
      ),
    onSuccess: (_data, value) => setRating(value),
  });
  return (
    <div
      role="group"
      aria-label={t("ai.feedback.label")}
      className="flex items-center gap-1.5 text-xs"
    >
      <span className="text-muted-foreground">{t("ai.feedback.label")}</span>
      {(["up", "down"] as const).map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={rating === value}
          disabled={send.isPending}
          onClick={() => send.mutate(value)}
          className="grid size-7 place-items-center rounded-md border border-border bg-surface text-muted-foreground hover:bg-muted hover:text-foreground aria-pressed:border-foreground aria-pressed:bg-muted aria-pressed:text-foreground"
        >
          {value === "up" ? (
            <ThumbsUp aria-hidden="true" className="size-3.5" strokeWidth={1.75} />
          ) : (
            <ThumbsDown aria-hidden="true" className="size-3.5" strokeWidth={1.75} />
          )}
          <span className="sr-only">{t(`ai.feedback.${value}`)}</span>
        </button>
      ))}
      {rating ? (
        <span role="status" className="text-muted-foreground">
          {t("ai.feedback.thanks")}
        </span>
      ) : null}
    </div>
  );
}

/** "AI-assisted" label for a record a person applied an AI draft to (FR-31-1). */
export function AiAssistedBadge({
  subjectType,
  subjectId,
}: {
  subjectType: string;
  subjectId: string;
}) {
  const { t } = useTranslation();
  const canUse = usePermission("ai.use");
  const assists = useQuery({
    queryKey: ["ai", "assists", subjectType, subjectId],
    enabled: canUse,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/ai/assists", {
          params: { query: { subject_type: subjectType, subject_id: subjectId } },
        }),
      ),
  });
  if (!assists.data?.results.length) return null;
  return (
    // A word, not a badge: AI help is stated in faded ink beside the record's own context.
    <span className="ml-2 inline-flex items-center gap-1 text-muted-foreground">
      <Sparkles aria-hidden="true" className="size-3.5 shrink-0" strokeWidth={1.75} />
      {t("ai.badge")}
    </span>
  );
}

export function AiNotice() {
  const { t } = useTranslation();
  return <p className="text-xs text-muted-foreground">{t("ai.disclaimer")}</p>;
}

export function AiError({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return <Alert tone="danger">{aiError(t, error)}</Alert>;
}

/** Proposed actions with confirm/discard: nothing runs until the person confirms. */
export function ProposalList({
  proposals,
  onDone,
}: {
  proposals: AiProposal[];
  onDone?: (proposal: AiProposal) => void;
}) {
  const { t } = useTranslation();
  const [state, setState] = useState<Record<string, AiProposal>>({});
  const decide = useMutation({
    mutationFn: async ({ id, step }: { id: string; step: "confirm" | "discard" }) => {
      const path = { params: { path: { id } } };
      return step === "confirm"
        ? unwrap(await api.POST("/api/v1/ai/proposals/{id}/confirm", path))
        : unwrap(await api.POST("/api/v1/ai/proposals/{id}/discard", path));
    },
    onSuccess: (proposal) => {
      setState((s) => ({ ...s, [proposal.id]: proposal }));
      onDone?.(proposal);
    },
  });
  if (!proposals.length) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold">{t("ai.command.proposals")}</h3>
      <ul className="space-y-2">
        {proposals.map((original) => {
          const p = state[original.id] ?? original;
          return (
            <li key={p.id} className="rounded-md border border-border bg-surface px-3 py-2 text-sm">
              <p>{p.summary}</p>
              {p.status === "proposed" ? (
                <div className="mt-1 flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => decide.mutate({ id: p.id, step: "confirm" })}
                    disabled={decide.isPending}
                    aria-label={`${t("ai.command.confirm")}: ${p.summary}`}
                  >
                    {t("ai.command.confirm")}
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => decide.mutate({ id: p.id, step: "discard" })}
                    disabled={decide.isPending}
                    aria-label={`${t("ai.command.discard")}: ${p.summary}`}
                  >
                    {t("ai.command.discard")}
                  </Button>
                </div>
              ) : (
                <p role="status" className="mt-1 text-xs font-medium">
                  {p.status === "executed"
                    ? t("ai.command.done")
                    : p.status === "failed"
                      ? t("ai.command.failed", { error: p.error })
                      : t("ai.command.discarded")}
                </p>
              )}
            </li>
          );
        })}
      </ul>
      <AiError error={decide.error} />
    </div>
  );
}

export interface ContentDraft {
  request: string;
  title: string;
  subject: string;
  body: string;
  meta_description: string;
}

/** "Draft with AI" for broadcasts, bios, website pages and job adverts (FR-31-8): a brief
 * in, a draft out, which the person chooses to use. */
export function AiContentHelper({
  kind,
  channel,
  tutor,
  title,
  onUse,
}: {
  kind: "broadcast" | "bio" | "page" | "job_ad";
  channel?: "email" | "sms";
  tutor?: string;
  title?: string;
  onUse: (draft: ContentDraft) => void;
}) {
  const { t } = useTranslation();
  const enabled = useAiFeature("content");
  const briefId = useId();
  const [open, setOpen] = useState(false);
  const [brief, setBrief] = useState("");
  const write = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/ai/content", {
          body: {
            kind,
            brief,
            channel: channel ?? "email",
            title: title ?? "",
            tutor: tutor ?? null,
            location: "",
          },
        }),
      ),
  });
  if (!enabled) return null;
  if (!open) {
    return (
      <Button type="button" size="sm" variant="secondary" onClick={() => setOpen(true)}>
        {t("ai.draft")}
      </Button>
    );
  }
  const draft = write.data;
  return (
    <section
      aria-label={t("ai.content.title")}
      className="space-y-2 rounded-md border border-border bg-surface p-3"
    >
      <label htmlFor={briefId} className="text-sm font-medium">
        {t("ai.content.brief")}
      </label>
      <textarea
        id={briefId}
        rows={3}
        value={brief}
        onChange={(e) => setBrief(e.target.value)}
        className="w-full rounded-md border border-field bg-surface px-3 py-2 text-sm"
      />
      <div className="flex gap-2">
        <Button type="button" size="sm" loading={write.isPending} onClick={() => write.mutate()}>
          {t("ai.content.write")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="text-muted-foreground"
          onClick={() => setOpen(false)}
        >
          {t("common.cancel")}
        </Button>
      </div>
      <AiError error={write.error} />
      {draft ? (
        <div className="space-y-2" aria-live="polite">
          {draft.title ? <p className="font-medium">{draft.title}</p> : null}
          {draft.subject ? (
            <p className="text-sm">
              {t("ai.content.subject")}: {draft.subject}
            </p>
          ) : null}
          <p className="rounded-md border border-border px-3 py-2 text-sm whitespace-pre-wrap">
            {draft.body}
          </p>
          {draft.warnings.map((w) => (
            <Alert key={w} tone="warning">
              {w}
            </Alert>
          ))}
          <AiNotice />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              onClick={() => {
                onUse(draft);
                setOpen(false);
              }}
            >
              {t("ai.useDraft")}
            </Button>
            <AiFeedback request={draft.request} />
          </div>
        </div>
      ) : null}
    </section>
  );
}

/** A language picker for "explain to parent" (empty: the contact's preferred language). */
export function LanguageSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <SelectField
      label={t("ai.progress.language")}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      options={[
        { value: "", label: t("ai.progress.sameLanguage") },
        ...["fr", "es", "de", "pl", "ro", "ur", "pa", "ar", "zh"].map((code) => ({
          value: code,
          label: t(`ai.languages.${code}`),
        })),
      ]}
    />
  );
}
