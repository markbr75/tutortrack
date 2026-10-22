import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api } from "../api";
import { useAiFeature } from "./ai";
import { useEnquiryTriage, type EnquiryTriage } from "./enquiryTriage";
import {
  AiContentHelper,
  AiError,
  AiFeedback,
  AiNotice,
  LanguageSelect,
  ProposalList,
} from "./AiParts";

type Extracted = components["schemas"]["AIExtractedEnquiry"];

// --- inbox (FR-31-3) ----------------------------------------------------------------------------

/** "Suggest reply": fills the composer with a draft the person edits and sends. */
export function AiReplySuggest({
  threadId,
  current,
  onSuggest,
}: {
  threadId: string;
  current: string;
  onSuggest: (text: string) => void;
}) {
  const { t } = useTranslation();
  const enabled = useAiFeature("inbox");
  const [draft, setDraft] = useState<{ request: string; reply: string } | null>(null);
  const suggest = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/ai/threads/{thread_id}/reply", {
          params: { path: { thread_id: threadId } },
        }),
      ),
    onSuccess: (body) => {
      setDraft(body);
      onSuggest(body.reply);
    },
  });
  if (!enabled) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        size="sm"
        variant="secondary"
        loading={suggest.isPending}
        onClick={() => suggest.mutate()}
      >
        {t("ai.inbox.suggest")}
      </Button>
      {draft ? (
        <AiFeedback request={draft.request} draftText={draft.reply} finalText={current} />
      ) : null}
      <AiError error={suggest.error} />
    </div>
  );
}

/** Summary and intent for a conversation, with routing proposals when configured. */
export function AiThreadTools({ threadId }: { threadId: string }) {
  const { t } = useTranslation();
  const enabled = useAiFeature("inbox");
  const queryClient = useQueryClient();
  const path = { params: { path: { thread_id: threadId } } };
  const insight = useQuery({
    queryKey: ["ai", "insight", threadId],
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/ai/thread-insights", { params: { query: { thread: threadId } } }),
      ),
  });
  const summary = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/ai/threads/{thread_id}/summary", path)),
  });
  const classify = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/ai/threads/{thread_id}/classify", path)),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["ai", "insight", threadId] }),
  });
  if (!enabled) return null;
  const current = classify.data ?? insight.data?.results[0];
  return (
    <div className="space-y-2 rounded-md border border-border bg-surface p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          loading={summary.isPending}
          onClick={() => summary.mutate()}
        >
          {t("ai.inbox.summarise")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          loading={classify.isPending}
          onClick={() => classify.mutate()}
        >
          {t("ai.inbox.classify")}
        </Button>
        {current ? (
          <span className="text-xs text-muted-foreground tabular-nums">
            {t("ai.inbox.intent", {
              intent: t(`ai.inbox.intents.${current.intent}`),
              confidence: current.confidence,
            })}
          </span>
        ) : null}
      </div>
      <AiError error={summary.error ?? classify.error} />
      {summary.data ? (
        <div aria-live="polite" className="space-y-1">
          <h3 className="font-semibold">{t("ai.inbox.summary")}</h3>
          <p>{summary.data.summary}</p>
          {summary.data.action_items.length ? (
            <ul className="list-disc pl-5">
              {summary.data.action_items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
          <AiFeedback request={summary.data.request} />
        </div>
      ) : null}
      {classify.data?.proposal ? (
        <ProposalList
          proposals={[classify.data.proposal]}
          onDone={() => void queryClient.invalidateQueries({ queryKey: ["threads"] })}
        />
      ) : null}
    </div>
  );
}

// --- enquiries (FR-31-4) --------------------------------------------------------------------------

/** Paste an email or message; the form is filled in for the person to check and save. */
export function AiEnquiryExtract({ onExtract }: { onExtract: (data: Extracted) => void }) {
  const { t } = useTranslation();
  const enabled = useAiFeature("enquiry");
  const textId = useId();
  const [text, setText] = useState("");
  const extract = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/ai/enquiries/extract", { body: { text } })),
    onSuccess: (body) => onExtract(body.extracted),
  });
  if (!enabled) return null;
  return (
    <div className="space-y-2 sm:col-span-3">
      <label htmlFor={textId} className="text-sm font-medium">
        {t("ai.enquiry.paste")}
      </label>
      <textarea
        id={textId}
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="w-full rounded-md border border-field bg-surface px-3 py-2 text-sm"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={!text.trim()}
          loading={extract.isPending}
          onClick={() => extract.mutate()}
        >
          {t("ai.enquiry.extract")}
        </Button>
        {extract.data ? (
          <>
            <span role="status" className="text-xs">
              {t("ai.enquiry.filled")}
            </span>
            <AiFeedback request={extract.data.request} />
          </>
        ) : null}
      </div>
      <AiError error={extract.error} />
    </div>
  );
}

/** Triage: next steps, a draft reply, and field changes as a proposal to confirm. */

/** "Triage with AI": a small secondary action (for a panel header or the page actions). */
export function AiEnquiryTriageButton({ triage }: { triage: EnquiryTriage }) {
  const { t } = useTranslation();
  if (!triage.enabled) return null;
  return (
    <Button
      type="button"
      size="sm"
      variant="secondary"
      loading={triage.triage.isPending}
      onClick={() => triage.triage.mutate()}
    >
      {t("ai.enquiry.triage")}
    </Button>
  );
}

/** The triage's suggested next steps and reply, on the clean leaf (nothing until asked). */
export function AiEnquiryTriageResult({
  triage,
  onApplied,
  className,
}: {
  triage: EnquiryTriage;
  onApplied: () => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const data = triage.triage.data;
  if (!triage.enabled || (!data && !triage.triage.error)) return null;
  return (
    <section aria-label={t("ai.enquiry.triage")} className={className}>
      <AiError error={triage.triage.error} />
      {data ? (
        <div className="space-y-2 text-sm" aria-live="polite">
          <h3 className="font-semibold">{t("ai.enquiry.nextSteps")}</h3>
          <ul className="list-disc pl-5">
            {data.next_steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ul>
          {data.priority ? <p>{t("ai.enquiry.priority", { priority: data.priority })}</p> : null}
          <h3 className="font-semibold">{t("ai.enquiry.reply")}</h3>
          {data.reply_subject ? <p className="font-medium">{data.reply_subject}</p> : null}
          <p className="rounded-md border border-border px-3 py-2 whitespace-pre-wrap">
            {data.reply_body}
          </p>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="-ml-3"
            onClick={() => void navigator.clipboard?.writeText(data.reply_body)}
          >
            {t("ai.copy")}
          </Button>
          {data.proposal ? <ProposalList proposals={[data.proposal]} onDone={onApplied} /> : null}
          <AiNotice />
          <AiFeedback request={data.request} />
        </div>
      ) : null}
    </section>
  );
}

/** The button and its result together (used where there is no panel to host them). */
export function AiEnquiryTriage({
  enquiryId,
  onApplied,
}: {
  enquiryId: string;
  onApplied: () => void;
}) {
  const triage = useEnquiryTriage(enquiryId);
  if (!triage.enabled) return null;
  return (
    <div className="space-y-3">
      <AiEnquiryTriageButton triage={triage} />
      <AiEnquiryTriageResult triage={triage} onApplied={onApplied} />
    </div>
  );
}

// --- progress reports (FR-31-2) -----------------------------------------------------------------

/** "Explain to parent": plain words, optionally translated, for the person to use. */
export function AiExplainToParent({
  text,
  student,
  onUse,
}: {
  text: string;
  student?: string;
  onUse: (text: string) => void;
}) {
  const { t } = useTranslation();
  const enabled = useAiFeature("parent_rewrite");
  const [language, setLanguage] = useState("");
  const rewrite = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/ai/rewrite", {
          body: { text, language, student: student ?? null },
        }),
      ),
  });
  if (!enabled) return null;
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-end gap-2">
        <LanguageSelect value={language} onChange={setLanguage} />
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={!text.trim()}
          loading={rewrite.isPending}
          onClick={() => rewrite.mutate()}
        >
          {t("ai.progress.explain")}
        </Button>
      </div>
      <AiError error={rewrite.error} />
      {rewrite.data ? (
        <div aria-live="polite" className="space-y-1">
          <p className="rounded-md border border-border px-3 py-2 whitespace-pre-wrap">
            {rewrite.data.text}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" onClick={() => onUse(rewrite.data.text)}>
              {t("ai.useDraft")}
            </Button>
            <AiFeedback request={rewrite.data.request} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

// --- job adverts (FR-31-8) ------------------------------------------------------------------------

/** Draft a job advert for a tutor vacancy (E18) to paste into the opening. */
export function AiJobAdvert() {
  const { t } = useTranslation();
  const [chosen, setChosen] = useState<{ title: string; body: string } | null>(null);
  return (
    <section aria-label={t("ai.jobAd.title")} className="space-y-2 text-sm">
      <h2 className="text-base font-semibold">{t("ai.jobAd.title")}</h2>
      <AiContentHelper kind="job_ad" onUse={(d) => setChosen({ title: d.title, body: d.body })} />
      {chosen ? (
        <div className="space-y-1 rounded-md border border-border px-3 py-2">
          <p className="font-medium">{chosen.title}</p>
          <p className="whitespace-pre-wrap">{chosen.body}</p>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="-ml-3"
            onClick={() => void navigator.clipboard?.writeText(`${chosen.title}\n\n${chosen.body}`)}
          >
            {t("ai.copy")}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

// --- matching (FR-31-6) -----------------------------------------------------------------------------

export function AiMatchExplain({ jobId, tutorId }: { jobId: string; tutorId: string }) {
  const { t } = useTranslation();
  const enabled = useAiFeature("matching");
  const explain = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/ai/matching/explain", { body: { job: jobId, tutor: tutorId } }),
      ),
  });
  if (!enabled) return null;
  return (
    <div className="mt-1 space-y-1 text-xs">
      <Button
        type="button"
        size="sm"
        variant="ghost"
        loading={explain.isPending}
        onClick={() => explain.mutate()}
      >
        {t("ai.matching.explain")}
      </Button>
      <AiError error={explain.error} />
      {explain.data ? (
        <div aria-live="polite" className="space-y-1">
          <p>{explain.data.explanation}</p>
          <p className="font-medium">{t("ai.matching.intro")}</p>
          <p className="rounded-md border border-border px-3 py-2 whitespace-pre-wrap">
            {explain.data.intro_message}
          </p>
          <AiFeedback request={explain.data.request} />
        </div>
      ) : null}
    </div>
  );
}
