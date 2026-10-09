import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";

import { api } from "../api";

type Field = components["schemas"]["TemplateField"];
type Answers = Record<string, unknown>;

function Input({
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
    return (
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
    );
  }
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
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

/** Write and submit a lesson report on a phone (E16-T03). */
export function TutorReportPage({ reportId }: { reportId: string }) {
  const { t } = useTranslation();
  const path = { params: { path: { id: reportId } } };
  const report = useQuery({
    queryKey: ["tutor", "report", reportId],
    queryFn: async () => unwrap(await api.GET("/api/v1/lesson-reports/{id}", path)),
  });
  const [answers, setAnswers] = useState<Answers | null>(null);
  useEffect(() => {
    if (report.data && answers === null) setAnswers(report.data.answers as Answers);
  }, [report.data, answers]);
  const save = useMutation({
    mutationFn: async (kind: "draft" | "submit") =>
      kind === "draft"
        ? unwrap(
            await api.PUT("/api/v1/lesson-reports/{id}", {
              ...path,
              body: { answers: answers ?? {} },
            }),
          )
        : unwrap(
            await api.POST("/api/v1/lesson-reports/{id}/submit", {
              ...path,
              body: { answers: answers ?? {} },
            }),
          ),
    onSuccess: () => void report.refetch(),
  });
  if (report.isPending || answers === null)
    return <Spinner className="size-6" label={t("grid.loading")} />;
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
      {r.template_fields.map((field) => (
        <Input
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
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
    </form>
  );
}
