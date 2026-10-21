import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Button,
  PageHeader,
  Panel,
  PanelRow,
  PanelRows,
  SelectField,
  Spinner,
  Tabs,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { PolicyOverrides, TemplateAssignments } from "../g3/DeliveryOverrides";

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
  max_free_per_term: null,
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

type ScopeType = components["schemas"]["CancellationPolicyScopeEnum"];

/** The organisation policy, or (gap G3) an override for one branch, service, job or
 * client: the most specific active policy wins (FR-09-3). */
export function PolicyForm({
  scopeType = "organisation",
  scopeId = null,
  scopeName = "",
}: {
  scopeType?: ScopeType;
  scopeId?: string | null;
  scopeName?: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const policies = useQuery({
    queryKey: ["cancellation-policies"],
    queryFn: async () => unwrap(await api.GET("/api/v1/cancellation-policies")),
  });
  const current = policies.data?.find(
    (p) => p.scope_type === scopeType && (p.scope_id ?? null) === scopeId,
  );
  const [rules, setRules] = useState<Rules | null>(null);
  const value = rules ?? current?.rules ?? DEFAULT_RULES;
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: current?.name ?? (scopeName || t("delivery.settings.policies")),
        scope_type: scopeType,
        scope_id: scopeId,
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
  if (policies.isPending) return <Spinner label={t("grid.loading")} />;
  const update = (change: Partial<Rules>) => setRules({ ...value, ...change });

  const makeup = value.makeup_credit ?? DEFAULT_RULES.makeup_credit!;
  return (
    <form
      aria-label={scopeName || t("delivery.settings.policies")}
      className="rounded-xl border border-border bg-surface"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="grid gap-4 px-5 py-4 sm:grid-cols-2">
        <div className="sm:col-span-2 sm:max-w-sm">
          <TextField
            type="number"
            min={0}
            label={t("delivery.settings.freeWindow")}
            className="tabular-nums"
            value={String(value.free_window_hours ?? 24)}
            onChange={(e) => update({ free_window_hours: Number(e.target.value) })}
          />
        </div>
        <TextField
          type="number"
          min={0}
          label={t("delivery.settings.maxFree")}
          className="tabular-nums"
          value={value.max_free_per_month == null ? "" : String(value.max_free_per_month)}
          onChange={(e) =>
            update({ max_free_per_month: e.target.value === "" ? null : Number(e.target.value) })
          }
        />
        <TextField
          type="number"
          min={0}
          label={t("g3.delivery.maxFreeTerm")}
          hint={t("g3.delivery.maxFreeTermHint")}
          className="tabular-nums"
          value={value.max_free_per_term == null ? "" : String(value.max_free_per_term)}
          onChange={(e) =>
            update({ max_free_per_term: e.target.value === "" ? null : Number(e.target.value) })
          }
        />
      </div>
      <div className="border-t border-border">
        <div
          aria-hidden="true"
          className="grid grid-cols-[minmax(0,1fr)_5.5rem_5.5rem] gap-x-3 border-b border-rule px-5 py-2.5 text-xs font-semibold text-muted-foreground sm:grid-cols-[minmax(0,1fr)_8rem_8rem]"
        >
          <span>{t("designS5.policy.situation")}</span>
          <span>{t("delivery.settings.charge")}</span>
          <span>{t("delivery.settings.pay")}</span>
        </div>
        {PAIRS.map(([key, label]) => (
          <fieldset
            key={key}
            className="grid grid-cols-[minmax(0,1fr)_5.5rem_5.5rem] items-center gap-x-3 border-b border-rule px-5 py-2 last:border-0 sm:grid-cols-[minmax(0,1fr)_8rem_8rem]"
          >
            <legend className="float-left text-sm">{t(`delivery.settings.${label}`)}</legend>
            <TextField
              type="number"
              min={0}
              max={100}
              size="sm"
              hideLabel
              className="tabular-nums"
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
              size="sm"
              hideLabel
              className="tabular-nums"
              label={t("delivery.settings.pay")}
              value={value[key]?.pay_percent ?? "0"}
              onChange={(e) =>
                update({ [key]: { ...value[key], pay_percent: e.target.value } } as Partial<Rules>)
              }
            />
          </fieldset>
        ))}
      </div>
      <div className="space-y-3 border-t border-border px-5 py-4">
        {(["on_free_cancellation", "on_tutor_cancellation"] as const).map((key) => (
          <label key={key} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
              checked={Boolean(makeup[key])}
              onChange={(e) => update({ makeup_credit: { ...makeup, [key]: e.target.checked } })}
            />
            {t(
              key === "on_free_cancellation"
                ? "delivery.settings.makeupFree"
                : "delivery.settings.makeupTutor",
            )}
          </label>
        ))}
        <div className="sm:max-w-sm">
          <TextField
            type="number"
            min={1}
            max={730}
            label={t("delivery.settings.makeupDays")}
            className="tabular-nums"
            value={String(makeup.valid_days ?? 60)}
            onChange={(e) =>
              update({ makeup_credit: { ...makeup, valid_days: Number(e.target.value) } })
            }
          />
        </div>
        <p className="text-xs text-muted-foreground">
          {t(
            scopeType === "organisation" ? "g3.delivery.orgPolicyHelp" : "g3.delivery.overrideHelp",
          )}
        </p>
        <ErrorList error={save.error} />
      </div>
      <div className="flex flex-wrap items-center justify-end gap-3 border-t border-border px-5 py-3">
        {save.isSuccess && !rules ? (
          <p role="status" className="text-sm text-muted-foreground">
            {t("delivery.settings.saved")}
          </p>
        ) : null}
        <Button type="submit" loading={save.isPending}>
          {t("delivery.settings.savePolicy")}
        </Button>
      </div>
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
  const [assigned, setAssigned] = useState({
    services: template?.services ?? [],
    subjects: template?.subjects ?? [],
    jobs: template?.jobs ?? [],
  });
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name,
        is_default: isDefault,
        ...assigned,
        fields: fields.map((f) => ({
          ...f,
          key:
            f.key ||
            keyFrom(
              f.label,
              fields.map((x) => x.key),
            ),
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
      className="rounded-xl border border-border bg-surface"
      aria-label={t("delivery.settings.templates")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="space-y-3 px-5 py-4 sm:max-w-md">
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
      </div>
      <fieldset className="border-t border-border">
        <legend className="float-left w-full px-5 pt-4 pb-1 text-base font-semibold">
          {t("delivery.settings.fields")}
        </legend>
        {fields.map((field, i) => (
          <div
            key={i}
            className="clear-both grid gap-3 border-b border-rule px-5 py-4 sm:grid-cols-2"
          >
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
              onChange={(e) => setField(i, { visibility: e.target.value as Field["visibility"] })}
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
                  className="mt-1 min-h-20 w-full rounded-md border border-field bg-surface px-3 py-2 text-sm"
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
        <div className="clear-both px-5 py-3">
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
        </div>
      </fieldset>
      <div className="space-y-3 border-t border-border px-5 py-4">
        <TemplateAssignments value={assigned} onChange={setAssigned} />
        <ErrorList error={save.error} />
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-5 py-3">
        {template ? (
          <Button
            type="button"
            variant="ghost"
            className="mr-auto text-muted-foreground"
            onClick={() => archive.mutate()}
          >
            {t("delivery.settings.archive")}
          </Button>
        ) : null}
        <Button type="submit" loading={save.isPending}>
          {t("delivery.settings.saveTemplate")}
        </Button>
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
  if (templates.isPending) return <Spinner label={t("grid.loading")} />;
  const current = templates.data?.find((x) => x.id === editing) ?? null;
  if (editing) return <TemplateEditor key={editing} template={current} onSaved={saved} />;
  const rows = templates.data ?? [];
  return (
    <Panel
      title={t("delivery.settings.templates")}
      aside={
        <Button size="sm" onClick={() => setEditing("new")}>
          {t("delivery.settings.newTemplate")}
        </Button>
      }
      flush
    >
      {rows.length ? (
        <PanelRows>
          {rows.map((template) => (
            <PanelRow key={template.id} className="flex items-center justify-between gap-3">
              <span className="min-w-0">
                <span className="block font-medium">{template.name}</span>
                <span className="block text-xs text-muted-foreground">
                  {[
                    template.is_default ? t("delivery.settings.default") : "",
                    t("delivery.settings.version", { n: template.version }),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </span>
              <Button size="sm" variant="secondary" onClick={() => setEditing(template.id)}>
                {t("delivery.reports.open")}
                <span className="sr-only"> {template.name}</span>
              </Button>
            </PanelRow>
          ))}
        </PanelRows>
      ) : (
        <p className="px-5 py-4 text-sm text-muted-foreground">
          {t("designS5.policy.noTemplates")}
        </p>
      )}
    </Panel>
  );
}

/** Cancellation policy and lesson report templates (FR-09-3, FR-09-4). */
export function DeliverySettingsPage() {
  const { t } = useTranslation();
  const canPolicy = usePermission("delivery.policy.manage");
  const canTemplates = usePermission("delivery.template.manage");
  const tabs = [
    ...(canPolicy ? [{ key: "policies" as const, label: t("delivery.settings.policies") }] : []),
    ...(canPolicy ? [{ key: "overrides" as const, label: t("g3.delivery.overrides") }] : []),
    ...(canTemplates
      ? [{ key: "templates" as const, label: t("delivery.settings.templates") }]
      : []),
  ];
  const [tab, setTab] = useState<"policies" | "overrides" | "templates">(
    tabs[0]?.key ?? "policies",
  );
  return (
    <div>
      <PageHeader title={t("delivery.settings.title")} />
      <Tabs label={t("delivery.settings.title")} tabs={tabs} value={tab} onChange={setTab}>
        {tab === "policies" ? (
          <PolicyForm />
        ) : tab === "overrides" ? (
          <PolicyOverrides />
        ) : (
          <Templates />
        )}
      </Tabs>
    </div>
  );
}
