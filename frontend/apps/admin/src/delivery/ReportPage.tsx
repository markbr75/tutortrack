import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";

type Field = components["schemas"]["TemplateField"];
type Answers = Record<string, unknown>;
const LONG_TEXT = new Set(["rich_text", "homework", "next_steps"]);
const LISTS = new Set(["topics", "attachment"]);

function TextArea({
  label,
  value,
  onChange,
  disabled,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  hint?: string;
}) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {hint ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
      <textarea
        id={id}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className="min-h-24 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function ListInput({
  field,
  value,
  onChange,
  disabled,
}: {
  field: Field;
  value: string[];
  onChange: (value: string[]) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState("");
  return (
    <fieldset className="space-y-1">
      <legend className="text-sm font-medium">{field.label}</legend>
      <ul className="flex flex-wrap gap-2">
        {value.map((item) => (
          <li key={item} className="flex items-center gap-1 rounded bg-muted px-2 py-1 text-sm">
            {item}
            {!disabled ? (
              <button
                type="button"
                className="text-muted-foreground"
                aria-label={t("delivery.reports.removeItem", { item })}
                onClick={() => onChange(value.filter((v) => v !== item))}
              >
                ×
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {!disabled ? (
        <div className="flex items-end gap-2">
          <TextField
            label={t("delivery.reports.newItem", { label: field.label })}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => {
              if (draft.trim() && !value.includes(draft.trim())) onChange([...value, draft.trim()]);
              setDraft("");
            }}
          >
            {t("delivery.reports.addItem")}
          </Button>
        </div>
      ) : null}
    </fieldset>
  );
}

function FieldInput({
  field,
  value,
  onChange,
  disabled,
}: {
  field: Field;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const label = field.required ? `${field.label} *` : field.label;
  const hint = [field.help_text, t(`delivery.reports.visibility.${field.visibility}`)]
    .filter(Boolean)
    .join(" · ");
  if (LONG_TEXT.has(field.type))
    return (
      <TextArea
        label={label}
        hint={hint}
        value={(value as string) ?? ""}
        onChange={onChange}
        disabled={disabled}
      />
    );
  if (field.type === "rating")
    return (
      <fieldset>
        <legend className="text-sm font-medium">{label}</legend>
        <div className="mt-1 flex gap-3">
          {[1, 2, 3, 4, 5].map((n) => (
            <label key={n} className="flex items-center gap-1 text-sm">
              <input
                type="radio"
                name={field.key}
                checked={value === n}
                disabled={disabled}
                onChange={() => onChange(n)}
              />
              <span aria-label={t("delivery.reports.rating", { n })}>{n}</span>
            </label>
          ))}
        </div>
      </fieldset>
    );
  if (field.type === "select")
    return (
      <SelectField
        label={label}
        hint={hint}
        value={(value as string) ?? ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value || null)}
        options={[
          { value: "", label: "—" },
          ...(field.options ?? []).map((o) => ({ value: o, label: o })),
        ]}
      />
    );
  if (field.type === "multi_select" || field.type === "checklist") {
    const chosen = (value as string[]) ?? [];
    return (
      <fieldset>
        <legend className="text-sm font-medium">{label}</legend>
        <div className="mt-1 space-y-1">
          {(field.options ?? []).map((o) => (
            <label key={o} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={chosen.includes(o)}
                disabled={disabled}
                onChange={(e) =>
                  onChange(e.target.checked ? [...chosen, o] : chosen.filter((c) => c !== o))
                }
              />
              {o}
            </label>
          ))}
        </div>
      </fieldset>
    );
  }
  if (LISTS.has(field.type))
    return (
      <ListInput
        field={field}
        value={(value as string[]) ?? []}
        onChange={onChange}
        disabled={disabled}
      />
    );
  return (
    <TextField
      label={label}
      hint={hint}
      value={(value as string) ?? ""}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function Comments({ reportId }: { reportId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState<"staff" | "client">("staff");
  const key = ["lesson-report", reportId, "comments"];
  const comments = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/lesson-reports/{id}/comments", {
          params: { path: { id: reportId } },
        }),
      ),
  });
  const post = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/lesson-reports/{id}/comments", {
          params: { path: { id: reportId } },
          body: { body, visibility },
        }),
      ),
    onSuccess: () => {
      setBody("");
      void queryClient.invalidateQueries({ queryKey: key });
    },
  });
  return (
    <section aria-labelledby="comments-title" className="space-y-2">
      <h2 id="comments-title" className="text-lg font-semibold">
        {t("delivery.reports.comments")}
      </h2>
      <ul className="space-y-2">
        {(comments.data ?? []).map((c) => (
          <li key={c.id} className="rounded-md border border-border p-2 text-sm">
            <p className="text-xs text-muted-foreground">
              {c.author_name} · {formatDateTime(c.created_at, i18n.language)}
            </p>
            <p className="whitespace-pre-wrap">{c.body}</p>
          </li>
        ))}
      </ul>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (body.trim()) post.mutate();
        }}
      >
        <TextArea
          label={t("delivery.reports.comment")}
          value={body}
          onChange={setBody}
          disabled={false}
        />
        <SelectField
          label={t("delivery.reports.commentVisibility")}
          value={visibility}
          onChange={(e) => setVisibility(e.target.value as "staff" | "client")}
          options={[
            { value: "staff", label: t("delivery.reports.commentStaff") },
            { value: "client", label: t("delivery.reports.commentClient") },
          ]}
        />
        <Button type="submit" size="sm" disabled={post.isPending}>
          {t("delivery.reports.post")}
        </Button>
      </form>
    </section>
  );
}

/** Write, submit, review and share a lesson report (FR-09-5/6). Drafts autosave. */
export function ReportPage({ reportId }: { reportId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canWrite = usePermission("delivery.report.write");
  const canEditAny = usePermission("delivery.report.edit_any");
  const canApprove = usePermission("delivery.report.approve");
  const canShare = usePermission("delivery.report.share");
  const key = ["lesson-report", reportId];
  const report = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/lesson-reports/{id}", { params: { path: { id: reportId } } })),
  });
  const [answers, setAnswers] = useState<Answers | null>(null);
  const [dirty, setDirty] = useState(false);
  const [note, setNote] = useState("");
  const [returning, setReturning] = useState(false);
  const loadedFor = useRef<string | null>(null);

  useEffect(() => {
    if (report.data && loadedFor.current !== report.data.id) {
      loadedFor.current = report.data.id;
      setAnswers(report.data.answers as Answers);
    }
  }, [report.data]);

  const onSaved = (data: components["schemas"]["LessonReport"]) => {
    queryClient.setQueryData(key, data);
    void queryClient.invalidateQueries({ queryKey: ["lesson-reports"] });
  };
  const autosave = useMutation({
    mutationFn: async (body: Answers) =>
      unwrap(
        await api.PUT("/api/v1/lesson-reports/{id}", {
          params: { path: { id: reportId } },
          body: { answers: body },
        }),
      ),
    onSuccess: (data) => {
      setDirty(false);
      onSaved(data);
    },
  });
  useEffect(() => {
    if (!dirty || !answers) return;
    const timer = window.setTimeout(() => autosave.mutate(answers), 800);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- autosave identity changes per render
  }, [answers, dirty]);

  const act = useMutation({
    mutationFn: async (kind: "submit" | "approve" | "return" | "share") => {
      const path = { params: { path: { id: reportId } } };
      if (kind === "submit")
        return unwrap(
          await api.POST("/api/v1/lesson-reports/{id}/submit", {
            ...path,
            body: { answers: answers ?? {} },
          }),
        );
      if (kind === "approve")
        return unwrap(await api.POST("/api/v1/lesson-reports/{id}/approve", path));
      if (kind === "return")
        return unwrap(
          await api.POST("/api/v1/lesson-reports/{id}/return", { ...path, body: { note } }),
        );
      return unwrap(await api.POST("/api/v1/lesson-reports/{id}/share", path));
    },
    onSuccess: (data) => {
      setDirty(false);
      setReturning(false);
      onSaved(data);
    },
  });

  if (report.isPending || !answers) return <Spinner className="size-6" label={t("grid.loading")} />;
  if (!report.data) return <ErrorList error={report.error} />;
  const data = report.data;
  const written = data.status === "submitted" || data.status === "approved";
  const editable = canWrite && (!written || canEditAny);

  return (
    <div className="max-w-2xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">
          {t("delivery.reports.heading", { title: data.lesson_title })}
        </h1>
        <p className="text-sm text-muted-foreground">
          {formatDateTime(data.lesson_start, i18n.language)} · {data.tutor_name} ·{" "}
          {t(`delivery.reports.sla.${data.sla_state}`)} ·{" "}
          {t("delivery.reports.dueAt", { when: formatDateTime(data.due_at, i18n.language) })}
        </p>
      </header>
      {data.status === "returned" && data.returned_note ? (
        <Alert tone="warning">{t("delivery.reports.returned", { note: data.returned_note })}</Alert>
      ) : null}
      {data.pay_held ? <Alert tone="warning">{t("delivery.reports.payHeld")}</Alert> : null}
      {!editable ? <Alert>{t("delivery.reports.readOnly")}</Alert> : null}

      <form
        className="space-y-4"
        aria-label={data.lesson_title}
        onSubmit={(e) => {
          e.preventDefault();
          act.mutate("submit");
        }}
      >
        {data.template_fields.map((field) => (
          <FieldInput
            key={field.key}
            field={field}
            value={answers[field.key]}
            disabled={!editable}
            onChange={(value) => {
              setAnswers((current) => ({ ...(current ?? {}), [field.key]: value }));
              setDirty(true);
            }}
          />
        ))}
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {autosave.isPending
            ? t("delivery.reports.saving")
            : autosave.isSuccess && !dirty
              ? t("delivery.reports.saved")
              : ""}
        </p>
        <ErrorList error={act.error ?? autosave.error} />
        <div className="flex flex-wrap gap-2">
          {editable && !written ? (
            <Button type="submit" disabled={act.isPending}>
              {t("delivery.reports.submit")}
            </Button>
          ) : null}
          {canApprove && data.status === "submitted" ? (
            <>
              <Button type="button" onClick={() => act.mutate("approve")}>
                {t("delivery.reports.approve")}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setReturning(true)}>
                {t("delivery.reports.return")}
              </Button>
            </>
          ) : null}
          {canShare && written && !data.shared_at ? (
            <Button type="button" variant="secondary" onClick={() => act.mutate("share")}>
              {t("delivery.reports.share")}
            </Button>
          ) : null}
        </div>
        {data.shared_at ? (
          <p className="text-sm text-muted-foreground">
            {t("delivery.reports.sharedAt", {
              when: formatDateTime(data.shared_at, i18n.language),
            })}
          </p>
        ) : null}
      </form>
      {returning ? (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            act.mutate("return");
          }}
        >
          <TextArea
            label={t("delivery.reports.returnNote")}
            value={note}
            onChange={setNote}
            disabled={false}
          />
          <Button type="submit" variant="secondary">
            {t("delivery.reports.return")}
          </Button>
        </form>
      ) : null}
      <Comments reportId={reportId} />
    </div>
  );
}
