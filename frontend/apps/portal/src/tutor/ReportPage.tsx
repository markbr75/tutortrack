import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";

import { api } from "../api";
import { isNetworkError, isOffline, queueChange } from "../offline/client";
import { AiReportDrafter } from "./AiDrafts";
import { DictationButton } from "./Dictation";
import { markReportAssisted } from "./aiApi";

type Field = components["schemas"]["TemplateField"];
export type Answers = Record<string, unknown>;

export function ReportFieldInput({
  field,
  value,
  onChange,
  disabled,
}: {
  field: Field;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled: boolean;
}) {
  const id = useId();
  const { t } = useTranslation();
  // E21: curriculum topics to pick from; a matching name tags the lesson on submit.
  const topics = useQuery({
    queryKey: ["learning", "topics"],
    enabled: field.type === "topics" && !disabled,
    staleTime: 300_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/learning/topics")),
  });
  const label = field.required ? `${field.label} *` : field.label;
  if (field.type === "rating") {
    return (
      <SelectField
        label={label}
        value={value ? String(value) : ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        options={[
          { value: "", label: "—" },
          ...[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) })),
        ]}
      />
    );
  }
  if (field.type === "select") {
    return (
      <SelectField
        label={label}
        value={(value as string) ?? ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value || null)}
        options={[
          { value: "", label: "—" },
          ...(field.options ?? []).map((o) => ({ value: o, label: o })),
        ]}
      />
    );
  }
  if (field.type === "multi_select" || field.type === "checklist") {
    const chosen = (value as string[]) ?? [];
    return (
      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">{label}</legend>
        {(field.options ?? []).map((o) => (
          <label key={o} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-5"
              checked={chosen.includes(o)}
              disabled={disabled}
              onChange={(e) =>
                onChange(e.target.checked ? [...chosen, o] : chosen.filter((c) => c !== o))
              }
            />
            {o}
          </label>
        ))}
      </fieldset>
    );
  }
  if (field.type === "topics" || field.type === "attachment") {
    const list = (value as string[]) ?? [];
    return (
      <div className="space-y-2">
        <TextField
          label={label}
          hint={t("tutor.commaHint")}
          disabled={disabled}
          value={((value as string[]) ?? []).join(", ")}
          onChange={(e) =>
            onChange(
              e.target.value
                .split(",")
                .map((v) => v.trim())
                .filter(Boolean),
            )
          }
        />
        {field.type === "topics" && topics.data?.length && !disabled ? (
          <SelectField
            label={t("learning.tutor.addTopic")}
            value=""
            onChange={(e) => {
              if (e.target.value && !list.includes(e.target.value))
                onChange([...list, e.target.value]);
            }}
            options={[
              { value: "", label: t("learning.tutor.chooseTopic") },
              ...topics.data.map((x) => ({ value: x.name, label: `${x.curriculum}: ${x.name}` })),
            ]}
          />
        ) : null}
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <DictationButton
          value={(value as string) ?? ""}
          onChange={onChange}
          disabled={disabled}
          fieldLabel={field.label}
        />
      </div>
      <textarea
        id={id}
        disabled={disabled}
        className="min-h-24 w-full rounded-md border border-border bg-background px-3 py-2 text-base"
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

/** Write and submit a lesson report on a phone (E16-T03). Without a signal the save is
 * kept on the phone and synced later, checked against the version it started from
 * (E16-T08). */
export function TutorReportPage({ reportId }: { reportId: string }) {
  const { t } = useTranslation();
  const path = { params: { path: { id: reportId } } };
  const etag = useRef<string | null>(null);
  const report = useQuery({
    queryKey: ["tutor", "report", reportId],
    queryFn: async () => {
      const result = await api.GET("/api/v1/lesson-reports/{id}", path);
      etag.current = result.response.headers.get("ETag");
      return unwrap(result);
    },
  });
  const [answers, setAnswers] = useState<Answers | null>(null);
  const [aiRequest, setAiRequest] = useState<string | null>(null);
  useEffect(() => {
    if (report.data && answers === null) setAnswers(report.data.answers as Answers);
  }, [report.data, answers]);
  const save = useMutation({
    mutationFn: async (kind: "draft" | "submit"): Promise<"saved" | "queued"> => {
      const body = { answers: answers ?? {} };
      const queue = async (key?: string) => {
        await queueChange(
          {
            kind: "report.save",
            label: report.data?.lesson_title ?? "",
            lessonId: report.data?.lesson ?? "",
            reportId,
            body: { ...body, submit: kind === "submit" },
            etag: etag.current,
          },
          key,
        );
        return "queued" as const;
      };
      if (isOffline()) return queue();
      const key = crypto.randomUUID();
      try {
        if (kind === "draft") {
          unwrap(await api.PUT("/api/v1/lesson-reports/{id}", { ...path, body }));
        } else {
          unwrap(
            await api.POST("/api/v1/lesson-reports/{id}/submit", {
              ...path,
              body,
              headers: { "Idempotency-Key": `${key}:submit` },
            }),
          );
        }
        return "saved";
      } catch (error) {
        if (isNetworkError(error)) return queue(key);
        throw error;
      }
    },
    onSuccess: (outcome, kind) => {
      if (outcome === "saved") void report.refetch();
      // E31: a report written from an AI draft is flagged AI-assisted when submitted.
      if (outcome === "saved" && kind === "submit" && aiRequest) {
        void markReportAssisted(aiRequest, reportId).catch(() => undefined);
      }
    },
  });
  if (report.isPending || answers === null) return <Spinner label={t("grid.loading")} />;
  const r = report.data;
  if (!r) return null;
  const written = r.status === "submitted" || r.status === "approved";
  return (
    <form
      className="space-y-4"
      aria-label={r.lesson_title}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate("submit");
      }}
    >
      <h1 className="text-xl font-semibold">{t("tutor.reportFor", { title: r.lesson_title })}</h1>
      {r.returned_note ? <Alert tone="warning">{r.returned_note}</Alert> : null}
      {!written ? (
        <AiReportDrafter
          reportId={reportId}
          onDraft={(draft) => {
            setAiRequest(draft.request);
            setAnswers((a) => ({ ...(a ?? {}), ...draft.answers }));
          }}
        />
      ) : null}
      {r.template_fields.map((field) => (
        <ReportFieldInput
          key={field.key}
          field={field}
          value={answers[field.key]}
          disabled={written}
          onChange={(v) => setAnswers((a) => ({ ...(a ?? {}), [field.key]: v }))}
        />
      ))}
      {written ? (
        <Alert tone="success">{t("tutor.reportSubmitted")}</Alert>
      ) : (
        <div className="flex gap-2">
          <Button type="submit" disabled={save.isPending}>
            {t("tutor.submitReport")}
          </Button>
          <Button type="button" variant="secondary" onClick={() => save.mutate("draft")}>
            {t("tutor.saveDraft")}
          </Button>
        </div>
      )}
      {save.data === "queued" ? <Alert>{t("pwa.reportQueued")}</Alert> : null}
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
    </form>
  );
}
