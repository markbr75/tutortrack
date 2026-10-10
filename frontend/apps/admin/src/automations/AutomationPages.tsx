import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";

import { api, usePermission } from "../api";

type Schema = components["schemas"]["AutomationSchema"];
type Automation = components["schemas"]["Automation"];
type Run = components["schemas"]["AutomationRun"];

type Condition = { field: string; op: string; value?: unknown };
type Conditions = { all?: Condition[]; any?: Condition[] } | Condition | Record<string, never>;
export type Step = {
  type: "action" | "wait" | "branch";
  action?: string;
  config?: Record<string, unknown>;
  hours?: number;
  days?: number;
  until?: string;
  if?: Condition;
  then?: Step[];
  else?: Step[];
};

const NO_VALUE = ["is_empty", "is_not_empty", "changed"];
const linkClass = "underline underline-offset-2";

function useSchema() {
  return useQuery({
    queryKey: ["automation-schema"],
    queryFn: async () => unwrap(await api.GET("/api/v1/automation-schema")),
    staleTime: 5 * 60_000,
  });
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="space-y-3 rounded-lg border border-border p-4">
      <h2 className="font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function describeTrigger(a: Automation, schema: Schema | undefined, t: (k: string) => string) {
  const config = a.trigger_config as Record<string, string>;
  if (a.trigger_type === "event") {
    return schema?.triggers.find((tr) => tr.event === config.event)?.label ?? config.event;
  }
  return t(`automations.triggers.${a.trigger_type}`);
}

// --- list, recipes and runs ----------------------------------------------------------------

type Tab = "automations" | "recipes" | "runs";

/** Automations, the recipe library and the run log (FR-14-4..6). */
export function AutomationsPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("automations");
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t("automations.title")}</h1>
        <Link to="/automations/$id" params={{ id: "new" }} className={linkClass}>
          {t("automations.new")}
        </Link>
      </div>
      <Tabs
        label={t("automations.title")}
        tabs={[
          { key: "automations", label: t("automations.title") },
          { key: "recipes", label: t("automations.recipes") },
          { key: "runs", label: t("automations.runs") },
        ]}
        value={tab}
        onChange={setTab}
      >
        {tab === "automations" ? <AutomationList /> : null}
        {tab === "recipes" ? <RecipeList onInstalled={() => setTab("automations")} /> : null}
        {tab === "runs" ? <RunList /> : null}
      </Tabs>
    </div>
  );
}

function AutomationList() {
  const { t } = useTranslation();
  const schema = useSchema();
  const queryClient = useQueryClient();
  const canManage = usePermission("automation.manage");
  const list = useQuery({
    queryKey: ["automations"],
    queryFn: async () => unwrap(await api.GET("/api/v1/automations")),
  });
  const toggle = useMutation({
    mutationFn: async (a: Automation) => {
      const path = { params: { path: { id: a.id } } };
      return unwrap(
        a.enabled
          ? await api.POST("/api/v1/automations/{id}/disable", path)
          : await api.POST("/api/v1/automations/{id}/enable", path),
      );
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["automations"] }),
  });
  if (!list.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  if (list.data.length === 0)
    return <p className="text-sm text-muted-foreground">{t("automations.none")}</p>;
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {list.data.map((a) => (
        <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
          <span>
            <Link
              to="/automations/$id"
              params={{ id: a.id }}
              className={`font-medium ${linkClass}`}
            >
              {a.name}
            </Link>
            <span className="block text-xs text-muted-foreground">
              {describeTrigger(a, schema.data, t)} · {t("automations.version", { n: a.version })}
            </span>
          </span>
          {canManage ? (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={a.enabled}
                onChange={() => toggle.mutate(a)}
                aria-label={t("automations.enabledFor", { name: a.name })}
              />
              {a.enabled ? t("automations.on") : t("automations.off")}
            </label>
          ) : (
            <span>{a.enabled ? t("automations.on") : t("automations.off")}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function RecipeList({ onInstalled }: { onInstalled: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("automation.manage");
  const recipes = useQuery({
    queryKey: ["automation-recipes"],
    queryFn: async () => unwrap(await api.GET("/api/v1/automation-recipes")),
  });
  const install = useMutation({
    mutationFn: async (key: string) =>
      unwrap(
        await api.POST("/api/v1/automation-recipes/{key}/install", { params: { path: { key } } }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["automations"] });
      void queryClient.invalidateQueries({ queryKey: ["automation-recipes"] });
      onInstalled();
    },
  });
  if (!recipes.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  return (
    <ul className="grid gap-3 md:grid-cols-2">
      {recipes.data.map((r) => (
        <li key={r.key} className="space-y-2 rounded-lg border border-border p-3 text-sm">
          <h3 className="font-medium">{r.name}</h3>
          <p className="text-muted-foreground">{r.description}</p>
          {r.installed ? (
            <span className="text-xs">{t("automations.installed")}</span>
          ) : canManage ? (
            <Button size="sm" onClick={() => install.mutate(r.key)} disabled={install.isPending}>
              {t("automations.install")}
            </Button>
          ) : null}
        </li>
      ))}
      {install.error ? <Alert tone="danger">{install.error.message}</Alert> : null}
    </ul>
  );
}

function RunRows({ runs }: { runs: Run[] }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const retry = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/automation-runs/{id}/retry", { params: { path: { id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["automation-runs"] }),
  });
  if (runs.length === 0)
    return <p className="text-sm text-muted-foreground">{t("automations.noRuns")}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th scope="col">{t("automations.automation")}</th>
            <th scope="col">{t("automations.record")}</th>
            <th scope="col">{t("automations.started")}</th>
            <th scope="col">{t("automations.status")}</th>
            <th scope="col">
              <span className="sr-only">{t("automations.actions")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="border-t border-border align-top">
              <td>
                {r.automation_name} (v{r.version})
              </td>
              <td>
                {r.subject_type} {(r.subject_id ?? "").slice(0, 8)}
              </td>
              <td>{formatDateTime(r.started_at, i18n.language)}</td>
              <td>
                {t(`automations.runStatus.${r.status}`)}
                {r.error ? <span className="block text-xs text-red-700">{r.error}</span> : null}
              </td>
              <td>
                {r.status === "failed" ? (
                  <Button size="sm" variant="secondary" onClick={() => retry.mutate(r.id)}>
                    {t("automations.retry")}
                  </Button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunList() {
  const { t } = useTranslation();
  const runs = useQuery({
    queryKey: ["automation-runs"],
    queryFn: async () => unwrap(await api.GET("/api/v1/automation-runs")),
  });
  if (!runs.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  return <RunRows runs={runs.data.results} />;
}

// --- builder ---------------------------------------------------------------------------------

function ConditionRow({
  value,
  onChange,
  onRemove,
  fields,
  operators,
}: {
  value: Condition;
  onChange: (c: Condition) => void;
  onRemove?: () => void;
  fields: { path: string; label: string }[];
  operators: string[];
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-end gap-2">
      <SelectField
        label={t("automations.field")}
        value={value.field}
        onChange={(e) => onChange({ ...value, field: e.target.value })}
        options={[
          { value: "", label: "—" },
          ...fields.map((f) => ({ value: f.path, label: f.label })),
        ]}
      />
      <SelectField
        label={t("automations.operator")}
        value={value.op}
        onChange={(e) => onChange({ ...value, op: e.target.value })}
        options={operators.map((o) => ({ value: o, label: t(`automations.ops.${o}`) }))}
      />
      {NO_VALUE.includes(value.op) ? null : (
        <TextField
          label={t("automations.value")}
          value={String(value.value ?? "")}
          onChange={(e) => onChange({ ...value, value: e.target.value })}
        />
      )}
      {onRemove ? (
        <Button size="sm" variant="secondary" onClick={onRemove}>
          {t("automations.remove")}
        </Button>
      ) : null}
    </div>
  );
}

function fieldLabels(schema: Schema, subject: string) {
  const s = schema.subjects.find((x) => x.key === subject);
  return (s?.fields ?? []).map((f) => ({ path: f.path, label: f.label }));
}

function ActionForm({
  step,
  onChange,
  schema,
  subject,
}: {
  step: Step;
  onChange: (s: Step) => void;
  schema: Schema;
  subject: string;
}) {
  const { t } = useTranslation();
  const config = step.config ?? {};
  const actions = schema.actions.filter(
    (a) => a.subjects.length === 0 || a.subjects.includes(subject),
  );
  const action = schema.actions.find((a) => a.key === step.action);
  const subjectDef = schema.subjects.find((x) => x.key === subject);
  const set = (name: string, value: unknown) =>
    onChange({ ...step, config: { ...config, [name]: value } });
  return (
    <div className="space-y-2">
      <SelectField
        label={t("automations.action")}
        value={step.action ?? ""}
        onChange={(e) => onChange({ ...step, action: e.target.value, config: {} })}
        options={[
          { value: "", label: "—" },
          ...actions.map((a) => ({
            value: a.key,
            label: a.allowed ? a.label : `${a.label} (${t("automations.noPermission")})`,
          })),
        ]}
      />
      {action?.fields.map((f) => {
        const label = f.required ? `${f.label} *` : f.label;
        if (f.type === "multi") {
          const options = f.name === "to" ? (subjectDef?.recipients ?? f.choices) : f.choices;
          const chosen = (config[f.name] as string[] | undefined) ?? [];
          return (
            <fieldset key={f.name} className="text-sm">
              <legend>{label}</legend>
              {options.map((o) => (
                <label key={o} className="mr-3 inline-flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={chosen.includes(o)}
                    onChange={(e) =>
                      set(f.name, e.target.checked ? [...chosen, o] : chosen.filter((c) => c !== o))
                    }
                  />
                  {t(`automations.options.${o}`, { defaultValue: o })}
                </label>
              ))}
            </fieldset>
          );
        }
        if (f.type === "choice") {
          return (
            <SelectField
              key={f.name}
              label={label}
              value={String(config[f.name] ?? "")}
              onChange={(e) => set(f.name, e.target.value)}
              options={[
                { value: "", label: "—" },
                ...f.choices.map((c) => ({ value: c, label: c })),
              ]}
            />
          );
        }
        if (f.type === "template") {
          return (
            <div key={f.name} className="space-y-1">
              <label className="block text-sm font-medium" htmlFor={`f-${f.name}`}>
                {label}
              </label>
              <textarea
                id={`f-${f.name}`}
                className="w-full rounded-md border border-border p-2 text-sm"
                rows={f.name === "body" ? 4 : 1}
                value={String(config[f.name] ?? "")}
                onChange={(e) => set(f.name, e.target.value)}
              />
              <SelectField
                label={t("automations.insertVariable")}
                value=""
                onChange={(e) =>
                  e.target.value &&
                  set(f.name, `${String(config[f.name] ?? "")}{{ ${e.target.value} }}`)
                }
                options={[
                  { value: "", label: "—" },
                  { value: "recipient.first_name", label: t("automations.recipientFirstName") },
                  ...(subjectDef?.fields ?? []).map((x) => ({ value: x.path, label: x.label })),
                ]}
              />
            </div>
          );
        }
        return (
          <TextField
            key={f.name}
            label={label}
            type={f.type === "number" ? "number" : "text"}
            value={String(config[f.name] ?? "")}
            onChange={(e) => set(f.name, e.target.value)}
          />
        );
      })}
    </div>
  );
}

function StepList({
  steps,
  onChange,
  schema,
  subject,
  depth = 0,
}: {
  steps: Step[];
  onChange: (steps: Step[]) => void;
  schema: Schema;
  subject: string;
  depth?: number;
}) {
  const { t } = useTranslation();
  const fields = fieldLabels(schema, subject);
  const replace = (i: number, step: Step) => onChange(steps.map((s, j) => (j === i ? step : s)));
  const remove = (i: number) => onChange(steps.filter((_s, j) => j !== i));
  const move = (i: number, by: number) => {
    const next = [...steps];
    const [item] = next.splice(i, 1);
    if (item) next.splice(Math.max(0, Math.min(next.length, i + by)), 0, item);
    onChange(next);
  };
  const add = (type: Step["type"]) =>
    onChange([
      ...steps,
      type === "action"
        ? { type, action: "", config: {} }
        : type === "wait"
          ? { type, hours: 24 }
          : { type, if: { field: "", op: "equals", value: "" }, then: [], else: [] },
    ]);
  return (
    <ol className="space-y-3">
      {steps.map((step, i) => (
        <li key={i} className="space-y-2 rounded-md border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <strong>
              {i + 1}. {t(`automations.stepTypes.${step.type}`)}
            </strong>
            <span className="flex gap-1">
              <Button size="sm" variant="secondary" onClick={() => move(i, -1)} disabled={i === 0}>
                {t("automations.up")}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => move(i, 1)}
                disabled={i === steps.length - 1}
              >
                {t("automations.down")}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => remove(i)}>
                {t("automations.remove")}
              </Button>
            </span>
          </div>
          {step.type === "action" ? (
            <ActionForm
              step={step}
              onChange={(s) => replace(i, s)}
              schema={schema}
              subject={subject}
            />
          ) : null}
          {step.type === "wait" ? (
            <div className="flex flex-wrap gap-2">
              <TextField
                label={t("automations.hours")}
                type="number"
                min={0}
                value={String(step.hours ?? "")}
                onChange={(e) =>
                  replace(i, { ...step, hours: Number(e.target.value) || 0, until: undefined })
                }
              />
              <TextField
                label={t("automations.days")}
                type="number"
                min={0}
                value={String(step.days ?? "")}
                onChange={(e) =>
                  replace(i, { ...step, days: Number(e.target.value) || 0, until: undefined })
                }
              />
            </div>
          ) : null}
          {step.type === "branch" ? (
            <div className="space-y-2">
              <ConditionRow
                value={step.if ?? { field: "", op: "equals" }}
                onChange={(c) => replace(i, { ...step, if: c })}
                fields={fields}
                operators={schema.operators}
              />
              {(["then", "else"] as const).map((arm) => (
                <div key={arm} className="border-l-2 border-border pl-3">
                  <p className="text-sm font-medium">{t(`automations.${arm}`)}</p>
                  <StepList
                    steps={step[arm] ?? []}
                    onChange={(s) => replace(i, { ...step, [arm]: s })}
                    schema={schema}
                    subject={subject}
                    depth={depth + 1}
                  />
                </div>
              ))}
            </div>
          ) : null}
        </li>
      ))}
      <li className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => add("action")}>
          {t("automations.addAction")}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => add("wait")}>
          {t("automations.addWait")}
        </Button>
        {depth < 2 ? (
          <Button size="sm" variant="secondary" onClick={() => add("branch")}>
            {t("automations.addBranch")}
          </Button>
        ) : null}
      </li>
    </ol>
  );
}

type Draft = {
  name: string;
  trigger_type: "event" | "schedule" | "date" | "manual";
  trigger_config: Record<string, unknown>;
  match: "all" | "any";
  conditions: Condition[];
  steps: Step[];
};

function toDraft(a: Automation | undefined): Draft {
  if (!a) {
    return {
      name: "",
      trigger_type: "event",
      trigger_config: {},
      match: "all",
      conditions: [],
      steps: [],
    };
  }
  const c = a.conditions as Conditions;
  const list: Condition[] =
    "all" in c && c.all
      ? c.all
      : "any" in c && c.any
        ? c.any
        : "field" in c
          ? [c as Condition]
          : [];
  return {
    name: a.name,
    trigger_type: a.trigger_type,
    trigger_config: a.trigger_config as Record<string, unknown>,
    match: "any" in c && c.any ? "any" : "all",
    conditions: list,
    steps: a.steps as Step[],
  };
}

function TriggerForm({
  draft,
  set,
  schema,
}: {
  draft: Draft;
  set: (d: Draft) => void;
  schema: Schema;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const config = draft.trigger_config;
  const setConfig = (key: string, value: unknown) =>
    set({ ...draft, trigger_config: { ...config, [key]: value } });
  const subject = String(config.subject ?? "");
  const subjectDef = schema.subjects.find((s) => s.key === subject);
  const triggers = schema.triggers.filter(
    (tr) => !search || tr.label.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <div className="space-y-2">
      <SelectField
        label={t("automations.triggerType")}
        value={draft.trigger_type}
        onChange={(e) =>
          set({
            ...draft,
            trigger_type: e.target.value as Draft["trigger_type"],
            trigger_config: {},
          })
        }
        options={(["event", "schedule", "date", "manual"] as const).map((k) => ({
          value: k,
          label: t(`automations.triggers.${k}`),
        }))}
      />
      {draft.trigger_type === "event" ? (
        <>
          <TextField
            label={t("automations.searchEvents")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <SelectField
            label={t("automations.event")}
            value={String(config.event ?? "")}
            onChange={(e) => setConfig("event", e.target.value)}
            options={[
              { value: "", label: "—" },
              ...triggers.map((tr) => ({ value: tr.event, label: tr.label })),
            ]}
          />
        </>
      ) : (
        <SelectField
          label={t("automations.subject")}
          value={subject}
          onChange={(e) => setConfig("subject", e.target.value)}
          options={[
            { value: "", label: "—" },
            ...schema.subjects.map((s) => ({ value: s.key, label: s.label })),
          ]}
        />
      )}
      {draft.trigger_type === "schedule" ? (
        <div className="flex flex-wrap gap-2">
          <SelectField
            label={t("automations.frequency")}
            value={String(config.frequency ?? "")}
            onChange={(e) => setConfig("frequency", e.target.value)}
            options={[
              { value: "", label: "—" },
              ...["daily", "weekly", "monthly"].map((f) => ({
                value: f,
                label: t(`automations.frequencies.${f}`),
              })),
            ]}
          />
          {config.frequency === "weekly" ? (
            <SelectField
              label={t("automations.weekday")}
              value={String(config.weekday ?? 0)}
              onChange={(e) => setConfig("weekday", Number(e.target.value))}
              options={["mon", "tue", "wed", "thu", "fri", "sat", "sun"].map((d, i) => ({
                value: String(i),
                label: t(`automations.days7.${d}`),
              }))}
            />
          ) : null}
          {config.frequency === "monthly" ? (
            <TextField
              label={t("automations.dayOfMonth")}
              type="number"
              min={1}
              max={28}
              value={String(config.day ?? 1)}
              onChange={(e) => setConfig("day", Number(e.target.value))}
            />
          ) : null}
          <TextField
            label={t("automations.time")}
            type="time"
            value={String(config.time ?? "08:00")}
            onChange={(e) => setConfig("time", e.target.value)}
          />
        </div>
      ) : null}
      {draft.trigger_type === "date" ? (
        <div className="flex flex-wrap items-end gap-2">
          <SelectField
            label={t("automations.dateField")}
            value={String(config.field ?? "")}
            onChange={(e) => setConfig("field", e.target.value)}
            options={[
              { value: "", label: "—" },
              ...(subjectDef?.date_fields ?? []).map((f) => ({ value: f, label: f })),
            ]}
          />
          <TextField
            label={t("automations.offsetDays")}
            type="number"
            value={String(config.offset_days ?? 0)}
            onChange={(e) => setConfig("offset_days", Number(e.target.value))}
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={Boolean(config.anniversary)}
              onChange={(e) => setConfig("anniversary", e.target.checked)}
            />
            {t("automations.everyYear")}
          </label>
          <TextField
            label={t("automations.time")}
            type="time"
            value={String(config.time ?? "08:00")}
            onChange={(e) => setConfig("time", e.target.value)}
          />
        </div>
      ) : null}
    </div>
  );
}

/** The When → If → Then builder with a dry run (FR-14-4). */
export function AutomationBuilderPage({ id }: { id: string }) {
  const isNew = id === "new";
  const schema = useSchema();
  const automation = useQuery({
    queryKey: ["automation", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/automations/{id}", { params: { path: { id } } })),
    enabled: !isNew,
  });
  if (!schema.data || (!isNew && !automation.data)) return <Spinner className="size-5" label="…" />;
  return (
    <Builder
      key={automation.data?.version ?? "new"}
      id={id}
      schema={schema.data}
      automation={automation.data}
    />
  );
}

function Builder({
  id,
  schema,
  automation,
}: {
  id: string;
  schema: Schema;
  automation?: Automation;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canManage = usePermission("automation.manage");
  const [draft, setDraft] = useState<Draft>(() => toDraft(automation));
  const [record, setRecord] = useState("");
  const subject =
    draft.trigger_type === "event"
      ? (schema.triggers.find((tr) => tr.event === draft.trigger_config.event)?.subject ?? "")
      : String(draft.trigger_config.subject ?? "");
  const fields = fieldLabels(schema, subject);
  const body = () => ({
    name: draft.name,
    description: "",
    trigger_type: draft.trigger_type,
    trigger_config: draft.trigger_config,
    conditions: draft.conditions.length ? { [draft.match]: draft.conditions } : {},
    steps: draft.steps as unknown as Record<string, unknown>[],
    enabled: automation?.enabled ?? false,
    max_runs_per_record: automation?.max_runs_per_record ?? 1,
  });
  const save = useMutation({
    mutationFn: async () =>
      automation
        ? unwrap(
            await api.PUT("/api/v1/automations/{id}", { params: { path: { id } }, body: body() }),
          )
        : unwrap(await api.POST("/api/v1/automations", { body: body() })),
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ["automations"] });
      queryClient.setQueryData(["automation", saved.id], saved);
      if (!automation) void navigate({ to: "/automations/$id", params: { id: saved.id } });
    },
  });
  const test = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/automations/{id}/test", {
          params: { path: { id } },
          body: { subject_id: record },
        }),
      ),
  });
  const runs = useQuery({
    queryKey: ["automation-runs", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/automations/{id}/runs", { params: { path: { id } } })),
    enabled: Boolean(automation),
  });
  return (
    <div className="space-y-4">
      <p className="text-sm">
        <Link to="/automations" className={linkClass}>
          {t("automations.title")}
        </Link>
      </p>
      <h1 className="text-2xl font-semibold">
        {automation ? automation.name : t("automations.new")}
        {automation ? (
          <span className="ml-2 text-sm font-normal text-muted-foreground">
            {t("automations.version", { n: automation.version })} ·{" "}
            {automation.enabled ? t("automations.on") : t("automations.off")}
          </span>
        ) : null}
      </h1>
      <TextField
        label={t("automations.name")}
        value={draft.name}
        onChange={(e) => setDraft({ ...draft, name: e.target.value })}
      />
      <Card title={t("automations.when")}>
        <TriggerForm draft={draft} set={setDraft} schema={schema} />
      </Card>
      <Card title={t("automations.if")}>
        <SelectField
          label={t("automations.match")}
          value={draft.match}
          onChange={(e) => setDraft({ ...draft, match: e.target.value as Draft["match"] })}
          options={[
            { value: "all", label: t("automations.matchAll") },
            { value: "any", label: t("automations.matchAny") },
          ]}
        />
        {draft.conditions.map((c, i) => (
          <ConditionRow
            key={i}
            value={c}
            fields={fields}
            operators={schema.operators}
            onChange={(next) =>
              setDraft({
                ...draft,
                conditions: draft.conditions.map((x, j) => (j === i ? next : x)),
              })
            }
            onRemove={() =>
              setDraft({ ...draft, conditions: draft.conditions.filter((_x, j) => j !== i) })
            }
          />
        ))}
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            setDraft({
              ...draft,
              conditions: [...draft.conditions, { field: "", op: "equals", value: "" }],
            })
          }
        >
          {t("automations.addCondition")}
        </Button>
      </Card>
      <Card title={t("automations.then")}>
        {subject ? (
          <StepList
            steps={draft.steps}
            onChange={(steps) => setDraft({ ...draft, steps })}
            schema={schema}
            subject={subject}
          />
        ) : (
          <p className="text-sm text-muted-foreground">{t("automations.chooseTriggerFirst")}</p>
        )}
      </Card>
      {canManage ? (
        <div className="space-y-2">
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {automation ? t("automations.saveVersion") : t("automations.create")}
          </Button>
          {save.isSuccess ? <Alert tone="success">{t("automations.saved")}</Alert> : null}
          {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
        </div>
      ) : null}
      {automation ? (
        <Card title={t("automations.dryRun")}>
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              test.mutate();
            }}
          >
            <TextField
              label={t("automations.recordId")}
              value={record}
              onChange={(e) => setRecord(e.target.value)}
            />
            <Button type="submit" variant="secondary" disabled={!record}>
              {t("automations.test")}
            </Button>
          </form>
          {test.error ? <Alert tone="danger">{test.error.message}</Alert> : null}
          {test.data ? (
            <div className="space-y-1 text-sm">
              <p className="font-medium">
                {test.data.matched ? t("automations.wouldRun") : t("automations.wouldNotRun")}
              </p>
              <ol className="list-decimal pl-5">
                {test.data.steps.map((s) => (
                  <li key={s.key} className={s.ok ? "" : "text-red-700"}>
                    {s.description}
                  </li>
                ))}
              </ol>
            </div>
          ) : null}
        </Card>
      ) : null}
      {automation ? (
        <Card title={t("automations.runs")}>{runs.data ? <RunRows runs={runs.data} /> : null}</Card>
      ) : null}
    </div>
  );
}
