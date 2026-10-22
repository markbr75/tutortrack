import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  FormPanel,
  PanelFooter,
  RuledPanel,
  RuledTable,
  SelectField,
  Spinner,
  TextAreaField,
  TextField,
  type RuledColumn,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { SavedNote } from "../components/SavedNote";

/**
 * A register table in a ruled panel titled by what it lists: skeleton rows while it loads and
 * one faded-ink sentence when it is empty.
 */
export function Table({
  caption,
  columns,
  loading,
  empty,
  aside,
  description,
  footer,
  children,
}: {
  caption: string;
  columns: ReadonlyArray<RuledColumn>;
  loading?: boolean;
  /** The sentence shown instead of rows; pass it only when there are none. */
  empty?: string;
  aside?: ReactNode;
  description?: ReactNode;
  footer?: ReactNode;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <RuledPanel flush title={caption} aside={aside} description={description} footer={footer}>
      <RuledTable
        caption={caption}
        columns={columns}
        loading={loading}
        loadingLabel={t("grid.loading")}
        empty={empty}
      >
        {children}
      </RuledTable>
    </RuledPanel>
  );
}

export function Cell({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={className}>{children}</td>;
}

export function FormCard({
  title,
  submit,
  pending,
  error,
  onSubmit,
  description,
  children,
}: {
  title: string;
  submit: string;
  pending?: boolean;
  error?: Error | null;
  onSubmit: () => void;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <FormPanel
      title={title}
      description={description}
      submit={submit}
      pending={pending}
      onSubmit={onSubmit}
      error={error ? <Alert tone="danger">{error.message}</Alert> : null}
    >
      {children}
    </FormPanel>
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
  return (
    <div className="sm:col-span-full">
      <TextAreaField
        label={label}
        rows={rows}
        required={required}
        error={error}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
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
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm sm:col-span-full">
        <span>
          <span className="text-muted-foreground">{t("privacyCentre.person")}: </span>
          <span className="font-medium">{value.label}</span>{" "}
          <span className="text-muted-foreground">
            ({t(`privacyCentre.subjectTypes.${value.subject_type}`)})
          </span>
        </span>
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange(null)}>
          {t("privacyCentre.change")}
        </Button>
      </div>
    );
  }
  const list = (hits.data ?? []).filter((h) => HIT_TYPES[h.type]);
  return (
    <div className="sm:col-span-full">
      <TextField
        label={t("privacyCentre.findPerson")}
        hint={t("privacyCentre.findPersonHint")}
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {list.length ? (
        <ul className="mt-2 divide-y divide-rule rounded-md border border-border bg-surface">
          {list.map((h) => (
            <li key={`${h.type}:${h.id}`}>
              <button
                type="button"
                className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
                onClick={() =>
                  onChange({
                    subject_type: HIT_TYPES[h.type] as string,
                    subject_id: h.id,
                    label: h.title,
                  })
                }
              >
                <span className="font-medium">{h.title}</span>{" "}
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

/** Edit one settings area (``/settings/{area}``) from its registered schema, in a ruled panel
 * with Save in its footer. */
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
  if (!query.data) return <Spinner label={t("grid.loading")} />;
  return (
    <form
      className="max-w-3xl"
      aria-label={label}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <RuledPanel flush title={label}>
        <div className="max-w-2xl space-y-3 px-5 py-4">
          {query.data.schema
            .filter((d) => d.key.startsWith(`${area}.`))
            .map((d) => {
              const value = values[d.key];
              if (d.type === "bool") {
                return (
                  <CheckboxField
                    key={d.key}
                    label={d.label}
                    hint={d.help_text || undefined}
                    disabled={!canManage}
                    checked={Boolean(value)}
                    onChange={(e) => setValues({ ...values, [d.key]: e.target.checked })}
                  />
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
                  className={d.type === "int" ? "w-24 text-right tabular-nums" : undefined}
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
        </div>
        {canManage ? (
          <PanelFooter>
            <Button type="submit" loading={save.isPending}>
              {t("privacyCentre.saveSettings")}
            </Button>
            <SavedNote show={save.isSuccess} text={t("privacyCentre.saved")} />
          </PanelFooter>
        ) : null}
      </RuledPanel>
    </form>
  );
}
