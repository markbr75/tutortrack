import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";

import { api, fieldErrors, usePermission } from "../api";

export function Table({
  caption,
  headers,
  children,
}: {
  caption: string;
  headers: string[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="mb-2 text-left font-semibold">{caption}</caption>
        <thead>
          <tr className="text-left">
            {headers.map((h) => (
              <th key={h} scope="col" className="px-2 py-1">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Cell({ children }: { children?: ReactNode }) {
  return <td className="border-t border-border px-2 py-1 align-top">{children}</td>;
}

export function FormCard({
  title,
  submit,
  pending,
  error,
  onSubmit,
  children,
}: {
  title: string;
  submit: string;
  pending?: boolean;
  error?: Error | null;
  onSubmit: () => void;
  children: ReactNode;
}) {
  return (
    <form
      className="space-y-3 rounded-md border border-border p-4"
      aria-label={title}
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <h2 className="font-semibold">{title}</h2>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
      <Button type="submit" disabled={pending}>
        {submit}
      </Button>
    </form>
  );
}

export function TextArea({
  label,
  value,
  onChange,
  required,
  error,
  rows = 4,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  error?: string;
  rows?: number;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1 sm:col-span-2">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        rows={rows}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className="rounded-md border border-border bg-background p-2 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {error ? (
        <p id={`${id}-error`} className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export interface PersonRef {
  subject_type: string;
  subject_id: string;
  label: string;
}

const HIT_TYPES: Record<string, string> = {
  client: "people.client",
  contact: "people.contact",
  student: "people.student",
  tutor: "people.tutor",
};

/** Search people (⌘K search) and pick one as a data subject. */
export function PersonPicker({
  value,
  onChange,
}: {
  value: PersonRef | null;
  onChange: (person: PersonRef | null) => void;
}) {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const hits = useQuery({
    queryKey: ["search", q],
    enabled: q.trim().length >= 2,
    queryFn: async () => unwrap(await api.GET("/api/v1/search", { params: { query: { q } } })),
  });
  if (value) {
    return (
      <div className="flex items-center gap-2 text-sm sm:col-span-2">
        <span>
          {t("privacyCentre.person")}: <strong>{value.label}</strong> (
          {t(`privacyCentre.subjectTypes.${value.subject_type}`)})
        </span>
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange(null)}>
          {t("privacyCentre.change")}
        </Button>
      </div>
    );
  }
  const list = (hits.data ?? []).filter((h) => HIT_TYPES[h.type]);
  return (
    <div className="sm:col-span-2">
      <TextField
        label={t("privacyCentre.findPerson")}
        hint={t("privacyCentre.findPersonHint")}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {list.length ? (
        <ul className="mt-2 divide-y divide-border rounded-md border border-border">
          {list.map((h) => (
            <li key={`${h.type}:${h.id}`}>
              <button
                type="button"
                className="w-full px-3 py-2 text-left text-sm hover:bg-muted focus-visible:outline focus-visible:outline-2"
                onClick={() =>
                  onChange({
                    subject_type: HIT_TYPES[h.type] as string,
                    subject_id: h.id,
                    label: h.title,
                  })
                }
              >
                {h.title}{" "}
                <span className="text-muted-foreground">
                  ({t(`privacyCentre.subjectTypes.${HIT_TYPES[h.type]}`)})
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Edit one settings area (``/settings/{area}``) from its registered schema. */
export function AreaSettings({ area, label }: { area: string; label: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("org.settings.manage");
  const query = useQuery({
    queryKey: ["settings", area],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/settings/{area}", { params: { path: { area } } })),
  });
  const [values, setValues] = useState<Record<string, unknown>>({});
  useEffect(() => {
    if (query.data) setValues(query.data.values);
  }, [query.data]);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/settings/{area}", {
          params: { path: { area } },
          body: { values },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["settings", area], data),
  });
  const errors = fieldErrors(save.error);
  if (!query.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  return (
    <form
      className="max-w-2xl space-y-3"
      aria-label={label}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {query.data.schema
        .filter((d) => d.key.startsWith(`${area}.`))
        .map((d) => {
          const value = values[d.key];
          if (d.type === "bool") {
            return (
              <label key={d.key} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  disabled={!canManage}
                  checked={Boolean(value)}
                  onChange={(e) => setValues({ ...values, [d.key]: e.target.checked })}
                />
                {d.label}
              </label>
            );
          }
          if (d.type === "choice") {
            return (
              <SelectField
                key={d.key}
                label={d.label}
                hint={d.help_text || undefined}
                disabled={!canManage}
                value={String(value ?? "")}
                onChange={(e) => setValues({ ...values, [d.key]: e.target.value })}
                options={(d.choices ?? []).map((c) => ({
                  value: String(c.value),
                  label: String(c.label),
                }))}
              />
            );
          }
          return (
            <TextField
              key={d.key}
              label={d.label}
              hint={d.help_text || undefined}
              disabled={!canManage}
              type={d.type === "int" ? "number" : "text"}
              min={d.min_value}
              max={d.max_value}
              value={String(value ?? "")}
              error={errors[d.key]}
              onChange={(e) =>
                setValues({
                  ...values,
                  [d.key]: d.type === "int" ? Number(e.target.value) : e.target.value,
                })
              }
            />
          );
        })}
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
      {save.isSuccess ? <p role="status">{t("privacyCentre.saved")}</p> : null}
      {canManage ? (
        <Button type="submit" disabled={save.isPending}>
          {t("privacyCentre.saveSettings")}
        </Button>
      ) : null}
    </form>
  );
}
