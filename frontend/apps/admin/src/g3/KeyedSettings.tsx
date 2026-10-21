import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";

import { api, fieldErrors, usePermission } from "../api";

interface Definition {
  key: string;
  type: string;
  label: string;
  help_text?: string;
  choices?: { value: unknown; label: unknown }[];
  min_value?: number | null;
  max_value?: number | null;
  schema?: { items?: { enum?: string[] } };
}

/** A few registered settings of one area (gap G3), optionally for one branch (branch-level
 * overrides): booleans, choices, numbers, text and lists of choices (as checkboxes). */
export function KeyedSettings({
  area,
  keys,
  label,
  branch,
  optionLabel,
  units,
}: {
  area: string;
  keys: string[];
  label: string;
  branch?: string;
  optionLabel?: (key: string, value: string) => string;
  /** Short numeric settings shown as a narrow field with this unit after it ("%", "days"). */
  units?: Record<string, string>;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("org.settings.manage");
  const queryKey = ["settings", area, branch ?? ""];
  const query = useQuery({
    queryKey,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/settings/{area}", {
          params: { path: { area }, query: branch ? { branch } : {} },
        }),
      ),
  });
  const [values, setValues] = useState<Record<string, unknown>>({});
  useEffect(() => {
    if (query.data) setValues(query.data.values);
  }, [query.data]);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/settings/{area}", {
          params: { path: { area }, query: branch ? { branch } : {} },
          body: { values: Object.fromEntries(keys.map((k) => [k, values[k]])) },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(queryKey, data),
  });
  const errors = fieldErrors(save.error);
  if (!query.data) return <Spinner label={t("grid.loading")} />;
  const schema = (query.data.schema as Definition[]).filter((d) => keys.includes(d.key));
  const set = (key: string, value: unknown) => setValues((v) => ({ ...v, [key]: value }));
  return (
    <form
      className="max-w-2xl space-y-3"
      aria-label={label}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {schema.map((d) => {
        const value = values[d.key];
        if (d.type === "bool")
          return (
            <label key={d.key} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                disabled={!canManage}
                checked={Boolean(value)}
                onChange={(e) => set(d.key, e.target.checked)}
              />
              {d.label}
            </label>
          );
        if (d.type === "choice")
          return (
            <SelectField
              key={d.key}
              label={d.label}
              hint={d.help_text || undefined}
              disabled={!canManage}
              value={String(value ?? "")}
              onChange={(e) => set(d.key, e.target.value)}
              options={(d.choices ?? []).map((c) => ({
                value: String(c.value),
                label: String(c.label),
              }))}
            />
          );
        const options = d.schema?.items?.enum;
        if (d.type === "object" && options) {
          const chosen = Array.isArray(value) ? (value as string[]) : [];
          return (
            <fieldset key={d.key} className="space-y-1">
              <legend className="text-sm font-medium">{d.label}</legend>
              {d.help_text ? <p className="text-xs text-muted-foreground">{d.help_text}</p> : null}
              <div className="grid gap-1 sm:grid-cols-2">
                {options.map((o) => (
                  <label key={o} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="size-4"
                      disabled={!canManage}
                      checked={chosen.includes(o)}
                      onChange={(e) =>
                        set(
                          d.key,
                          e.target.checked ? [...chosen, o] : chosen.filter((c) => c !== o),
                        )
                      }
                    />
                    {optionLabel ? optionLabel(d.key, o) : o}
                  </label>
                ))}
              </div>
              {errors[d.key] ? (
                <p className="text-sm text-danger" role="alert">
                  {errors[d.key]}
                </p>
              ) : null}
            </fieldset>
          );
        }
        const unit = units?.[d.key];
        if (unit)
          return (
            <UnitField
              key={d.key}
              label={d.label}
              hint={d.help_text || undefined}
              unit={unit}
              disabled={!canManage}
              numeric={d.type === "int"}
              min={d.min_value ?? undefined}
              max={d.max_value ?? undefined}
              value={String(value ?? "")}
              error={errors[d.key]}
              onChange={(v) => set(d.key, d.type === "int" ? Number(v) : v)}
            />
          );
        return (
          <TextField
            key={d.key}
            label={d.label}
            hint={d.help_text || undefined}
            disabled={!canManage}
            type={d.type === "int" ? "number" : "text"}
            min={d.min_value ?? undefined}
            max={d.max_value ?? undefined}
            value={String(value ?? "")}
            error={errors[d.key]}
            onChange={(e) => set(d.key, d.type === "int" ? Number(e.target.value) : e.target.value)}
          />
        );
      })}
      {save.error && !Object.keys(errors).length ? (
        <Alert tone="danger">{save.error.message}</Alert>
      ) : null}
      {save.isSuccess ? <p role="status">{t("common.saved")}</p> : null}
      {canManage ? (
        <Button type="submit" disabled={save.isPending}>
          {t("common.save")}
        </Button>
      ) : null}
    </form>
  );
}

/** A narrow numeric field with its unit after it, wired like the shared fields. */
function UnitField({
  label,
  hint,
  unit,
  error,
  numeric,
  value,
  onChange,
  disabled,
  min,
  max,
}: {
  label: string;
  hint?: string;
  unit: string;
  error?: string;
  numeric: boolean;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  min?: number;
  max?: number;
}) {
  const id = useId();
  const described = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="flex items-center gap-2">
        <input
          id={id}
          type={numeric ? "number" : "text"}
          inputMode="decimal"
          min={min}
          max={max}
          value={value}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={described}
          onChange={(e) => onChange(e.target.value)}
          className="h-10 w-24 rounded-md border border-field bg-surface px-3 text-right text-sm tabular-nums aria-[invalid=true]:border-danger"
        />
        <span className="text-sm text-muted-foreground">{unit}</span>
      </div>
      {hint && !error ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
