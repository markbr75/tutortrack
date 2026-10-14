import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

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
}: {
  area: string;
  keys: string[];
  label: string;
  branch?: string;
  optionLabel?: (key: string, value: string) => string;
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
  if (!query.data) return <Spinner className="size-5" label={t("grid.loading")} />;
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
