import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";

type Rules = components["schemas"]["PolicyRules"];
type Field = components["schemas"]["TemplateFieldRequest"];
type FieldType = components["schemas"]["TemplateFieldTypeEnum"];
type Template = components["schemas"]["ReportTemplate"];

const PAIRS = [
  ["late_cancellation", "lateCancel"],
  ["no_show", "noShow"],
  ["absent_notified", "absentNotified"],
  ["late", "late"],
  ["tutor_cancellation", "tutorCancel"],
  ["admin_cancellation", "adminCancel"],
] as const;
const DEFAULT_RULES: Rules = {
  free_window_hours: 24,
  late_cancellation: { charge_percent: "100", pay_percent: "50" },
  no_show: { charge_percent: "100", pay_percent: "100" },
  absent_notified: { charge_percent: "0", pay_percent: "0" },
  late: { charge_percent: "100", pay_percent: "100" },
  tutor_cancellation: { charge_percent: "0", pay_percent: "0" },
  admin_cancellation: { charge_percent: "0", pay_percent: "0" },
  max_free_per_month: null,
  makeup_credit: { on_free_cancellation: false, on_tutor_cancellation: false, valid_days: 60 },
};
const TYPES: FieldType[] = [
  "rich_text",
  "text",
  "rating",
  "select",
  "multi_select",
  "checklist",
  "topics",
  "homework",
  "next_steps",
  "attachment",
];
const CHOICES = new Set<FieldType>(["select", "multi_select", "checklist"]);

function PolicyForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const policies = useQuery({
    queryKey: ["cancellation-policies"],
    queryFn: async () => unwrap(await api.GET("/api/v1/cancellation-policies")),
  });
  const current = policies.data?.find((p) => p.scope_type === "organisation");
  const [rules, setRules] = useState<Rules | null>(null);
  const value = rules ?? current?.rules ?? DEFAULT_RULES;
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: current?.name ?? t("delivery.settings.policies"),
        scope_type: "organisation" as const,
        scope_id: null,
        rules: value,
      };
      return current
        ? unwrap(
            await api.PUT("/api/v1/cancellation-policies/{id}", {
              params: { path: { id: current.id } },
              body,
            }),
          )
        : unwrap(await api.POST("/api/v1/cancellation-policies", { body }));
    },
    onSuccess: () => {
      setRules(null);
      void queryClient.invalidateQueries({ queryKey: ["cancellation-policies"] });
    },
  });
  if (policies.isPending) return <Spinner className="size-5" label={t("grid.loading")} />;
  const update = (change: Partial<Rules>) => setRules({ ...value, ...change });

  return (
    <form
      className="max-w-xl space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <TextField
        type="number"
        min={0}
        label={t("delivery.settings.freeWindow")}
        value={String(value.free_window_hours ?? 24)}
        onChange={(e) => update({ free_window_hours: Number(e.target.value) })}
      />
      {PAIRS.map(([key, label]) => (
        <fieldset key={key} className="grid grid-cols-2 gap-2">
          <legend className="col-span-2 text-sm font-semibold">
            {t(`delivery.settings.${label}`)}
          </legend>
          <TextField
            type="number"
            min={0}
            max={100}
            label={t("delivery.settings.charge")}
            value={value[key]?.charge_percent ?? "0"}
            onChange={(e) =>
              update({
                [key]: { ...value[key], charge_percent: e.target.value },
              } as Partial<Rules>)
            }
          />
          <TextField
            type="number"
            min={0}
            max={100}
            label={t("delivery.settings.pay")}
            value={value[key]?.pay_percent ?? "0"}
            onChange={(e) =>
              update({ [key]: { ...value[key], pay_percent: e.target.value } } as Partial<Rules>)
            }
          />
        </fieldset>
      ))}
      <TextField
        type="number"
        min={0}
        label={t("delivery.settings.maxFree")}
        value={value.max_free_per_month == null ? "" : String(value.max_free_per_month)}
        onChange={(e) =>
          update({ max_free_per_month: e.target.value === "" ? null : Number(e.target.value) })
        }
      />
      {(["on_free_cancellation", "on_tutor_cancellation"] as const).map((key) => (
        <label key={key} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={Boolean(value.makeup_credit?.[key])}
            onChange={(e) =>
              update({
                makeup_credit: {
                  ...(value.makeup_credit ?? DEFAULT_RULES.makeup_credit!),
                  [key]: e.target.checked,
                },
              })
            }
          />
          {t(key === "on_free_cancellation" ? "delivery.settings.makeupFree" : "delivery.settings.makeupTutor")}
        </label>
      ))}
      <TextField
        type="number"
        min={1}
        max={730}
        label={t("delivery.settings.makeupDays")}
        value={String(value.makeup_credit?.valid_days ?? 60)}
        onChange={(e) =>
          update({
            makeup_credit: {
              ...(value.makeup_credit ?? DEFAULT_RULES.makeup_credit!),
              valid_days: Number(e.target.value),
            },
          })
        }
      />
      <p className="text-sm text-muted-foreground">{t("delivery.settings.overridesHelp")}</p>
      <ErrorList error={save.error} />
      {save.isSuccess && !rules ? <Alert tone="success">{t("delivery.settings.saved")}</Alert> : null}
      <Button type="submit" disabled={save.isPending}>
        {t("delivery.settings.savePolicy")}
      </Button>
    </form>
  );
}

function keyFrom(label: string, taken: string[]): string {
  const base =
    label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^(\d)/, "f_$1")
      .slice(0, 30) || "field";
  let key = base;
  for (let n = 2; taken.includes(key); n += 1) key = `${base}_${n}`;
  return key;
}

function TemplateEditor({ template, onSaved }: { template: Template | null; onSaved: () => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState(template?.name ?? "");
  const [isDefault, setIsDefault] = useState(template?.is_default ?? false);
  const [fields, setFields] = useState<Field[]>(
    template?.fields ?? [
      { key: "covered", label: "", type: "rich_text", required: true, visibility: "student" },
    ],
  );
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name,
        is_default: isDefault,
        fields: fields.map((f) => ({
          ...f,
          key: f.key || keyFrom(f.label, fields.map((x) => x.key)),
          options: CHOICES.has(f.type) ? f.options : undefined,
        })),
      };
      return template
        ? unwrap(
            await api.PATCH("/api/v1/report-templates/{id}", {
              params: { path: { id: template.id } },
              body,
            }),
          )
        : unwrap(await api.POST("/api/v1/report-templates", { body }));
    },
    onSuccess: onSaved,
  });
  const archive = useMutation({
    mutationFn: async () =>
      api.DELETE("/api/v1/report-templates/{id}", { params: { path: { id: template!.id } } }),
    onSuccess: onSaved,
  });
  const setField = (i: number, change: Partial<Field>) =>
    setFields((current) => current.map((f, n) => (n === i ? { ...f, ...change } : f)));

  return (
    <form
      className="max-w-2xl space-y-4"
      aria-label={t("delivery.settings.templates")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <TextField
        label={t("delivery.settings.templateName")}
        value={name}
        required
        onChange={(e) => setName(e.target.value)}
      />
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4"
          checked={isDefault}
          onChange={(e) => setIsDefault(e.target.checked)}
        />
        {t("delivery.settings.default")}
      </label>
      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold">{t("delivery.settings.fields")}</legend>
        {fields.map((field, i) => (
          <div key={i} className="grid gap-2 rounded-md border border-border p-3 sm:grid-cols-2">
            <TextField
              label={t("delivery.settings.fieldLabel")}
              value={field.label}
              required
              onChange={(e) =>
                setField(i, {
                  label: e.target.value,
                  ...(template?.fields?.some((f) => f.key === field.key)
                    ? {}
                    : {
                        key: keyFrom(
                          e.target.value,
                          fields.filter((_f, n) => n !== i).map((f) => f.key),
                        ),
                      }),
                })
              }
            />
            <SelectField
              label={t("delivery.settings.fieldType")}
              value={field.type}
              onChange={(e) => setField(i, { type: e.target.value as FieldType })}
              options={TYPES.map((type) => ({
                value: type,
                label: t(`delivery.settings.types.${type}`),
              }))}
            />
            <SelectField
              label={t("delivery.settings.fieldVisibility")}
              value={field.visibility}
              onChange={(e) =>
                setField(i, { visibility: e.target.value as Field["visibility"] })
              }
              options={(["staff", "client", "student"] as const).map((v) => ({
                value: v,
                label: t(`delivery.reports.visibility.${v}`),
              }))}
            />
            <label className="flex items-center gap-2 self-end text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={field.required ?? false}
                onChange={(e) => setField(i, { required: e.target.checked })}
              />
              {t("delivery.settings.fieldRequired")}
            </label>
            {CHOICES.has(field.type) ? (
              <div className="sm:col-span-2">
                <label className="text-sm font-medium" htmlFor={`options-${i}`}>
                  {t("delivery.settings.fieldOptions")}
                </label>
                <textarea
                  id={`options-${i}`}
                  className="mt-1 min-h-20 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  value={(field.options ?? []).join("\n")}
                  onChange={(e) =>
                    setField(i, { options: e.target.value.split("\n").filter(Boolean) })
                  }
                />
              </div>
            ) : null}
            <div className="sm:col-span-2">
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setFields((current) => current.filter((_f, n) => n !== i))}
              >
                {t("delivery.settings.removeField", { label: field.label || field.key })}
              </Button>
            </div>
          </div>
        ))}
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() =>
            setFields((current) => [
              ...current,
              { key: "", label: "", type: "text", required: false, visibility: "client" },
            ])
          }
        >
          {t("delivery.settings.addField")}
        </Button>
      </fieldset>
      <ErrorList error={save.error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          {t("delivery.settings.saveTemplate")}
        </Button>
        {template ? (
          <Button type="button" variant="ghost" onClick={() => archive.mutate()}>
            {t("delivery.settings.archive")}
          </Button>
        ) : null}
      </div>
    </form>
  );
}

function Templates() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const templates = useQuery({
    queryKey: ["report-templates"],
    queryFn: async () => unwrap(await api.GET("/api/v1/report-templates")),
  });
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const saved = () => {
    setEditing(null);
    void queryClient.invalidateQueries({ queryKey: ["report-templates"] });
  };
  if (templates.isPending) return <Spinner className="size-5" label={t("grid.loading")} />;
  const current = templates.data?.find((x) => x.id === editing) ?? null;
  if (editing) return <TemplateEditor key={editing} template={current} onSaved={saved} />;
  return (
    <div className="space-y-3">
      <ul className="divide-y divide-border rounded-md border border-border">
        {(templates.data ?? []).map((template) => (
          <li key={template.id} className="flex items-center justify-between p-3 text-sm">
            <span>
              {template.name}
              {template.is_default ? ` · ${t("delivery.settings.default")}` : ""}
              <span className="ml-2 text-muted-foreground">
                {t("delivery.settings.version", { n: template.version })}
              </span>
            </span>
            <Button size="sm" variant="secondary" onClick={() => setEditing(template.id)}>
              {t("delivery.reports.open")}
              <span className="sr-only"> {template.name}</span>
            </Button>
          </li>
        ))}
      </ul>
      <Button size="sm" onClick={() => setEditing("new")}>
        {t("delivery.settings.newTemplate")}
      </Button>
    </div>
  );
}

/** Cancellation policy and lesson report templates (FR-09-3, FR-09-4). */
export function DeliverySettingsPage() {
  const { t } = useTranslation();
  const canPolicy = usePermission("delivery.policy.manage");
  const canTemplates = usePermission("delivery.template.manage");
  const tabs = [
    ...(canPolicy ? [{ key: "policies" as const, label: t("delivery.settings.policies") }] : []),
    ...(canTemplates
      ? [{ key: "templates" as const, label: t("delivery.settings.templates") }]
      : []),
  ];
  const [tab, setTab] = useState<"policies" | "templates">(tabs[0]?.key ?? "policies");
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("delivery.settings.title")}</h1>
      <Tabs label={t("delivery.settings.title")} tabs={tabs} value={tab} onChange={setTab}>
        {tab === "policies" ? <PolicyForm /> : <Templates />}
      </Tabs>
    </div>
  );
}
