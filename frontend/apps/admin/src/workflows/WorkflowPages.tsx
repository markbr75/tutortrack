import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  CheckboxField,
  NamePlate,
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
import { Link, useNavigate } from "@tanstack/react-router";
import { AlertCircle, ArrowDown, ArrowUp, Plus, Split, Trash2 } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { api, usePermission } from "../api";
import { RecordHeader } from "../components/RecordHeader";
import { eventLabel, useSchemas, type FieldSchema, type Schema } from "./common";
import { ComingUp, PreviewPanel } from "./Preview";
import { RunList, RunRows } from "./Runs";
import {
  allProblems,
  cardProblems,
  countSplits,
  dateOffset,
  fits,
  fromQuestions,
  MAX_SPLITS,
  MAX_STOPS,
  moveItem,
  newCard,
  newSplit,
  omit,
  questionsOf,
  setDateOffset,
  setWaitAmount,
  startOffsets,
  toCards,
  toSteps,
  waitAmount,
  waitMode,
  type Card,
  type Condition,
  type DoCard,
  type Problem,
  type SplitCard,
  type StartKind,
  type Step,
  type WaitMode,
} from "./sequence";

type Workflow = components["schemas"]["Automation"];
type ActionDef = Schema["actions"][number];
type RecordType = Schema["record_types"][number];
type Translate = (key: string, options?: Record<string, unknown>) => string;

const linkClass = "underline-offset-2 hover:underline";
const GROUPS = ["invoicing", "lessons", "sales", "expiry"] as const;
const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

/** Built-ins are changed with ``automation.builtin.manage``, custom ones with ``.manage``. */
function useCanChange(): (w?: Workflow) => boolean {
  const custom = usePermission("automation.manage");
  const builtin = usePermission("automation.builtin.manage");
  return (w) => (w?.kind === "builtin" ? builtin : custom);
}

// --- sentences ---------------------------------------------------------------------------------

function questionLabel(schema: Schema, key: string) {
  return schema.questions.find((q) => q.key === key)?.label ?? key;
}

function describeCondition(
  condition: Condition | null | undefined,
  schema: Schema,
  fields: FieldSchema | undefined,
  t: Translate,
): string {
  if (!condition || Object.keys(condition).length === 0) return "";
  const questions = questionsOf(condition);
  if (questions) return questions.map((q) => questionLabel(schema, q)).join(t("workflows.and"));
  const one = (c: Condition): string => {
    if (c.predicate) return questionLabel(schema, c.predicate);
    if (c.all) return c.all.map(one).join(t("workflows.and"));
    if (c.any) return c.any.map(one).join(t("workflows.or"));
    const label =
      fields?.subjects.flatMap((s) => s.fields).find((f) => f.path === c.field)?.label ?? c.field;
    const op = t(`automations.ops.${c.op ?? "equals"}`);
    return [label, op, c.value === undefined ? "" : String(c.value)].filter(Boolean).join(" ");
  };
  return one(condition);
}

function describeWait(wait: Step | null, record: RecordType | undefined, t: Translate): string {
  if (!wait) return t("workflows.when.now");
  const extras = [
    wait.at ? t("workflows.when.at", { time: wait.at }) : "",
    wait.business_day ? t("workflows.when.businessDay") : "",
    wait.quiet_hours ? t("workflows.when.quietHours") : "",
  ].filter(Boolean);
  let base: string;
  if (wait.until) {
    const date = record?.date_fields.find((f) => f.path === wait.until)?.label ?? wait.until;
    const { amount, unit } = dateOffset(wait);
    base =
      amount === 0
        ? t("workflows.when.onDate", { date })
        : t(amount < 0 ? `workflows.when.before_${unit}` : `workflows.when.after_${unit}`, {
            count: Math.abs(amount),
            date,
          });
  } else if (wait.until === "") {
    base = t("workflows.when.dateNotChosen");
  } else {
    const { amount, unit } = waitAmount(wait);
    base = amount ? t(`workflows.when.wait_${unit}`, { count: amount }) : t("workflows.when.today");
  }
  return [base, ...extras].join(", ");
}

function describeStart(
  w: { trigger_type: string; trigger_config: Record<string, unknown> },
  schema: Schema,
  t: Translate,
): string {
  const c = w.trigger_config;
  const record = schema.record_types.find((r) => r.key === c.subject);
  if (w.trigger_type === "event") {
    return c.event
      ? t("workflows.start.event", { label: eventLabel(schema, String(c.event)) })
      : t("workflows.start.chooseEvent");
  }
  if (w.trigger_type === "manual") {
    return t("workflows.start.manual", { record: record?.label.toLowerCase() ?? "" });
  }
  const time = String(c.time ?? "08:00");
  if (w.trigger_type === "schedule") {
    const each = record ? t("workflows.start.forEach", { record: record.label.toLowerCase() }) : "";
    const when =
      c.frequency === "weekly"
        ? t("workflows.start.weekly", {
            day: t(`automations.days7.${WEEKDAYS[Number(c.weekday ?? 0)]}`),
            time,
          })
        : c.frequency === "monthly"
          ? t("workflows.start.monthly", { day: Number(c.day ?? 1), time })
          : t("workflows.start.daily", { time });
    return [when, each].filter(Boolean).join(", ");
  }
  const field = record?.start_dates.find((d) => d.field === c.field);
  const date = field?.label ?? String(c.field ?? "");
  const { values, unit } = startOffsets(c);
  const parts = values.map((v) => {
    const amount = unit === "minutes" ? v / 60 : v;
    const u = unit === "minutes" ? "hours" : "days";
    if (amount === 0) return t("workflows.start.onThe");
    return t(amount < 0 ? `workflows.start.before_${u}` : `workflows.start.after_${u}`, {
      count: Math.abs(amount),
    });
  });
  const list = parts.join(t("workflows.and"));
  const sentence = t("workflows.start.date", {
    list,
    record: record?.label.toLowerCase() ?? "",
    date,
  });
  return unit === "days" ? `${sentence}, ${t("workflows.when.at", { time })}` : sentence;
}

function describeActions(actions: Step[], schema: Schema, t: Translate): string {
  if (actions.length === 0) return t("workflows.do.nothing");
  return actions
    .map(
      (a) => schema.actions.find((x) => x.key === a.action)?.label ?? t("workflows.do.notChosen"),
    )
    .join(t("workflows.then"));
}

function problemText(p: Problem, t: Translate): string {
  return p.code === "fillIn"
    ? t("workflows.problems.fillIn", { field: p.field })
    : t(`workflows.problems.${p.code}`);
}

// --- list ------------------------------------------------------------------------------------

type Tab = "builtin" | "custom" | "templates" | "runs";

/** Workflows: the built-in ones, the organisation's own, templates and runs (E33 FR-33-3). */
export function WorkflowsPage() {
  const { t } = useTranslation();
  const canManage = usePermission("automation.manage");
  const [tab, setTab] = useState<Tab>("builtin");
  return (
    <div>
      <PageHeader
        title={t("workflows.title")}
        description={t("workflows.help")}
        actions={
          canManage ? (
            <Link to="/workflows/$id" params={{ id: "new" }} className={buttonClass()}>
              {t("workflows.new")}
            </Link>
          ) : null
        }
      />
      <Tabs
        label={t("workflows.title")}
        tabs={[
          { key: "builtin", label: t("workflows.tabs.builtin") },
          { key: "custom", label: t("workflows.tabs.custom") },
          { key: "templates", label: t("workflows.tabs.templates") },
          { key: "runs", label: t("workflows.tabs.runs") },
        ]}
        value={tab}
        onChange={setTab}
      >
        {tab === "builtin" ? <WorkflowList kind="builtin" /> : null}
        {tab === "custom" ? <WorkflowList kind="custom" /> : null}
        {tab === "templates" ? <TemplateList onInstalled={() => setTab("custom")} /> : null}
        {tab === "runs" ? <RunList /> : null}
      </Tabs>
    </div>
  );
}

function StatusSwitch({ w }: { w: Workflow }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canChange = useCanChange()(w);
  const locked = w.enabled && w.builtin?.can_switch_off === false;
  const toggle = useMutation({
    mutationFn: async () => {
      const path = { params: { path: { id: w.id } } };
      return unwrap(
        w.enabled
          ? await api.POST("/api/v1/workflows/{id}/disable", path)
          : await api.POST("/api/v1/workflows/{id}/enable", path),
      );
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["workflows"] }),
  });
  const state = w.paused
    ? t("workflows.paused")
    : w.enabled
      ? t("workflows.on")
      : t("workflows.off");
  if (!canChange) {
    return <span className={w.enabled ? "text-sm" : "text-sm text-muted-foreground"}>{state}</span>;
  }
  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        className="size-4"
        checked={w.enabled}
        disabled={locked || toggle.isPending}
        aria-describedby={locked ? `locked-${w.id}` : undefined}
        onChange={() => toggle.mutate()}
        aria-label={t("workflows.switchFor", { name: w.name })}
      />
      <span className={w.enabled ? undefined : "text-muted-foreground"}>{state}</span>
      {locked ? (
        <span id={`locked-${w.id}`} className="sr-only">
          {t("workflows.cantSwitchOff")}
        </span>
      ) : null}
    </label>
  );
}

function WorkflowRows({ rows }: { rows: Workflow[] }) {
  const { t } = useTranslation();
  return (
    <PanelRows>
      {rows.map((w) => (
        <PanelRow key={w.id} className="hover:bg-muted/60">
          <NamePlate
            name={
              <Link to="/workflows/$id" params={{ id: w.id }} className={linkClass}>
                {w.name}
              </Link>
            }
            context={[
              w.edited ? t("workflows.edited") : null,
              w.builtin?.update_available ? t("workflows.newerDefault") : null,
              w.description || null,
            ]
              .filter(Boolean)
              .join(" · ")}
            aside={<StatusSwitch w={w} />}
          />
        </PanelRow>
      ))}
    </PanelRows>
  );
}

function WorkflowList({ kind }: { kind: "builtin" | "custom" }) {
  const { t } = useTranslation();
  const list = useQuery({
    queryKey: ["workflows"],
    queryFn: async () => unwrap(await api.GET("/api/v1/workflows")),
  });
  if (!list.data) return <Spinner label={t("grid.loading")} />;
  const rows = list.data.filter((w) => w.kind === kind);
  if (kind === "custom") {
    return (
      <Panel label={t("workflows.tabs.custom")} flush>
        {rows.length ? (
          <WorkflowRows rows={rows} />
        ) : (
          <p className="px-5 py-6 text-sm text-muted-foreground">{t("workflows.noCustom")}</p>
        )}
      </Panel>
    );
  }
  return (
    <div className="space-y-6">
      {GROUPS.map((group) => {
        const inGroup = rows.filter((w) => w.builtin?.group === group);
        if (!inGroup.length) return null;
        return (
          <Panel key={group} title={inGroup[0]?.builtin?.group_label ?? group} flush>
            <WorkflowRows rows={inGroup} />
          </Panel>
        );
      })}
    </div>
  );
}

function TemplateList({ onInstalled }: { onInstalled: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("automation.manage");
  const templates = useQuery({
    queryKey: ["automation-recipes"],
    queryFn: async () => unwrap(await api.GET("/api/v1/automation-recipes")),
  });
  const install = useMutation({
    mutationFn: async (key: string) =>
      unwrap(
        await api.POST("/api/v1/automation-recipes/{key}/install", { params: { path: { key } } }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      void queryClient.invalidateQueries({ queryKey: ["automation-recipes"] });
      onInstalled();
    },
  });
  if (!templates.data) return <Spinner label={t("grid.loading")} />;
  return (
    <div className="space-y-4">
      {install.error ? <Alert tone="danger">{install.error.message}</Alert> : null}
      <Panel label={t("workflows.tabs.templates")} flush>
        <PanelRows>
          {templates.data.map((r) => (
            <PanelRow key={r.key}>
              <NamePlate
                name={r.name}
                context={r.description}
                aside={
                  r.installed ? (
                    <span className="text-sm text-muted-foreground">{t("workflows.added")}</span>
                  ) : canManage ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => install.mutate(r.key)}
                      disabled={install.isPending}
                    >
                      {t("workflows.useTemplate")}
                    </Button>
                  ) : null
                }
              />
            </PanelRow>
          ))}
        </PanelRows>
      </Panel>
    </div>
  );
}

// --- editor ------------------------------------------------------------------------------------

type Draft = {
  name: string;
  trigger_type: StartKind;
  trigger_config: Record<string, unknown>;
  conditions: Condition;
  stop_when: string[];
  cards: Card[];
};

function toDraft(w: Workflow | undefined): Draft {
  return {
    name: w?.name ?? "",
    trigger_type: (w?.trigger_type ?? "event") as StartKind,
    trigger_config: (w?.trigger_config ?? {}) as Record<string, unknown>,
    conditions: (w?.conditions ?? {}) as Condition,
    stop_when: (w?.stop_when ?? []) as string[],
    cards: toCards((w?.steps ?? []) as Step[]),
  };
}

function subjectOf(draft: Draft, schema: Schema): string {
  if (draft.trigger_type === "event") {
    return schema.starts.events.find((e) => e.event === draft.trigger_config.event)?.subject ?? "";
  }
  return String(draft.trigger_config.subject ?? "");
}

function startProblems(draft: Draft, t: Translate): string[] {
  const c = draft.trigger_config;
  if (draft.trigger_type === "event" && !c.event) return [t("workflows.problems.chooseStart")];
  if (draft.trigger_type !== "event" && !c.subject) return [t("workflows.problems.chooseRecord")];
  if (draft.trigger_type === "date") {
    if (!c.field) return [t("workflows.problems.chooseDate")];
    if (startOffsets(c).values.length === 0) return [t("workflows.problems.howLong")];
  }
  return [];
}

/** The sequence editor: one timeline of cards, edited in place (E33 FR-33-3). */
export function WorkflowEditorPage({ id }: { id: string }) {
  const { t } = useTranslation();
  const isNew = id === "new";
  const { schema, fields } = useSchemas();
  const workflow = useQuery({
    queryKey: ["workflow", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/workflows/{id}", { params: { path: { id } } })),
    enabled: !isNew,
  });
  // The editor remounts on a new version, so the page keeps what the last save did.
  const [saved, setSaved] = useState<{ version: number; kind: "saved" | "reset" } | null>(null);
  if (!schema || (!isNew && !workflow.data)) return <Spinner label={t("grid.loading")} />;
  return (
    <Editor
      key={workflow.data?.version ?? "new"}
      id={id}
      schema={schema}
      fields={fields}
      workflow={workflow.data}
      saved={saved && saved.version === workflow.data?.version ? saved.kind : null}
      onSaved={setSaved}
    />
  );
}

function Editor({
  id,
  schema,
  fields,
  workflow,
  saved,
  onSaved,
}: {
  id: string;
  schema: Schema;
  fields: FieldSchema | undefined;
  workflow?: Workflow;
  saved: "saved" | "reset" | null;
  onSaved: (s: { version: number; kind: "saved" | "reset" }) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const builtIn = workflow?.kind === "builtin";
  const canChange = useCanChange()(workflow);
  const shows = fits((workflow?.steps ?? []) as Step[]);
  const editable = canChange && shows;
  const [draft, setDraft] = useState<Draft>(() => toDraft(workflow));
  const [open, setOpen] = useState<string | null>(workflow ? null : "start");
  const [dirty, setDirty] = useState(false);
  const update = (next: Draft) => {
    setDraft(next);
    setDirty(true);
  };
  const subject = subjectOf(draft, schema);
  const record = schema.record_types.find((r) => r.key === subject);
  const problems = [
    ...startProblems(draft, t),
    ...allProblems(draft.cards, schema.actions).map((p) => problemText(p, t)),
  ];

  // The sequence itself: what Save stores and Preview can try unsaved.
  const sequence = () => ({
    trigger_type: draft.trigger_type,
    trigger_config: draft.trigger_config,
    conditions: draft.conditions,
    steps: toSteps(draft.cards) as unknown as Record<string, unknown>[],
    stop_when: draft.stop_when,
  });
  const body = (enabled: boolean) => ({
    name: draft.name,
    description: workflow?.description ?? "",
    ...sequence(),
    enabled,
    max_runs_per_record: workflow?.max_runs_per_record ?? 1,
  });
  const save = useMutation({
    mutationFn: async (enabled: boolean) =>
      workflow
        ? unwrap(
            await api.PUT("/api/v1/workflows/{id}", {
              params: { path: { id } },
              body: body(enabled),
            }),
          )
        : unwrap(await api.POST("/api/v1/workflows", { body: body(enabled) })),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      onSaved({ version: result.version, kind: "saved" });
      queryClient.setQueryData(["workflow", result.id], result);
      if (!workflow) void navigate({ to: "/workflows/$id", params: { id: result.id } });
    },
  });
  const reset = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/workflows/{id}/reset-to-default", { params: { path: { id } } }),
      ),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      onSaved({ version: result.version, kind: "reset" });
      queryClient.setQueryData(["workflow", result.id], result);
    },
  });

  const pause = useMutation({
    mutationFn: async () => {
      const path = { params: { path: { id } } };
      return unwrap(
        workflow?.paused
          ? await api.POST("/api/v1/workflows/{id}/resume", path)
          : await api.POST("/api/v1/workflows/{id}/pause", path),
      );
    },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      queryClient.setQueryData(["workflow", id], { ...workflow, ...result });
    },
  });

  const setCards = (cards: Card[]) => update({ ...draft, cards });
  const splits = countSplits(draft.cards);
  const status = workflow
    ? [
        builtIn ? t("workflows.builtIn") : null,
        workflow.paused
          ? t("workflows.paused")
          : workflow.enabled
            ? t("workflows.on")
            : t("workflows.off"),
        workflow.edited ? t("workflows.edited") : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : undefined;

  return (
    <article>
      <RecordHeader
        back={<Link to="/workflows">{t("workflows.title")}</Link>}
        title={workflow ? workflow.name : t("workflows.new")}
        description={status}
      />
      <div className="max-w-3xl space-y-6">
        {workflow?.builtin?.update_available ? (
          <Alert tone="info">{t("workflows.updateAvailable")}</Alert>
        ) : null}
        {!shows ? <Alert tone="info">{t("workflows.tooComplex")}</Alert> : null}
        {builtIn && workflow?.description ? (
          <p className="text-sm text-muted-foreground">{workflow.description}</p>
        ) : null}
        {!builtIn && editable ? (
          <div className="max-w-md">
            <TextField
              label={t("workflows.name")}
              value={draft.name}
              onChange={(e) => update({ ...draft, name: e.target.value })}
            />
          </div>
        ) : null}

        <ol
          aria-label={t("workflows.timeline")}
          className="relative space-y-3 border-l-2 border-rule pl-5"
        >
          <TimelineItem>
            <StartCard
              draft={draft}
              schema={schema}
              fields={fields}
              builtIn={builtIn}
              editable={editable}
              open={open === "start"}
              onOpen={(o) => setOpen(o ? "start" : null)}
              onChange={update}
              problems={startProblems(draft, t)}
            />
          </TimelineItem>
          {editable ? (
            <AddHere
              label={t("workflows.addAt", { n: 1 })}
              onAdd={() => {
                setCards([newCard(), ...draft.cards]);
                setOpen("0");
              }}
              onSplit={
                splits < MAX_SPLITS
                  ? () => {
                      setCards([newSplit(), ...draft.cards]);
                      setOpen("0");
                    }
                  : undefined
              }
            />
          ) : null}
          {draft.cards.map((card, i) => (
            <CardItem
              key={i}
              index={i}
              path={String(i)}
              count={draft.cards.length}
              card={card}
              cards={draft.cards}
              onCards={setCards}
              schema={schema}
              fields={fields}
              record={record}
              editable={editable}
              open={open}
              setOpen={setOpen}
              splitsLeft={splits < MAX_SPLITS}
            />
          ))}
        </ol>

        {editable ? (
          <div className="space-y-3">
            {problems.length ? (
              <p className="flex items-center gap-1 text-sm font-medium text-danger">
                <AlertCircle aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.75} />
                {t("workflows.fixFirst", { count: problems.length })}
              </p>
            ) : null}
            {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
            {reset.error ? <Alert tone="danger">{reset.error.message}</Alert> : null}
            <div>
              {saved === "saved" && !dirty ? (
                <Alert tone="success">
                  {workflow?.runs_under_way
                    ? t("workflows.savedUnderWay", { count: workflow.runs_under_way })
                    : t("workflows.saved")}
                </Alert>
              ) : null}
              {saved === "reset" && !dirty ? (
                <Alert tone="success">{t("workflows.resetDone")}</Alert>
              ) : null}
            </div>
            {workflow ? (
              <p id="pause-help" className="text-xs text-muted-foreground">
                {workflow.paused ? t("workflows.pausedHelp") : t("workflows.pauseHelp")}
              </p>
            ) : null}
            {pause.error ? <Alert tone="danger">{pause.error.message}</Alert> : null}
            {dirty && workflow?.runs_under_way ? (
              <p className="text-sm text-muted-foreground">
                {t("workflows.underWay", { count: workflow.runs_under_way })}
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={() => save.mutate(workflow?.enabled ?? false)}
                loading={save.isPending}
                disabled={problems.length > 0 || (!dirty && Boolean(workflow))}
              >
                {t("workflows.save")}
              </Button>
              {!workflow?.enabled ? (
                <Button
                  variant="secondary"
                  onClick={() => save.mutate(true)}
                  loading={save.isPending}
                  disabled={problems.length > 0}
                >
                  {t("workflows.saveAndSwitchOn")}
                </Button>
              ) : null}
              {workflow ? (
                <Button
                  variant="ghost"
                  loading={pause.isPending}
                  onClick={() => pause.mutate()}
                  aria-describedby="pause-help"
                >
                  {workflow.paused ? t("workflows.resume") : t("workflows.pause")}
                </Button>
              ) : null}
              {builtIn && (workflow?.edited || workflow?.builtin?.update_available) ? (
                <Button
                  variant="ghost"
                  loading={reset.isPending}
                  onClick={() => {
                    if (window.confirm(t("workflows.confirmReset", { name: workflow?.name })))
                      reset.mutate();
                  }}
                >
                  {t("workflows.resetToDefault")}
                </Button>
              ) : null}
            </div>
          </div>
        ) : null}
        {workflow && (workflow.trigger_type === "schedule" || workflow.trigger_type === "date") ? (
          <ComingUp
            id={workflow.id}
            version={workflow.version}
            recordType={workflow.subject_type}
            changed={
              JSON.stringify([draft.trigger_type, draft.trigger_config]) !==
              JSON.stringify([workflow.trigger_type, workflow.trigger_config])
            }
          />
        ) : null}
        {workflow ? (
          <PreviewPanel
            id={workflow.id}
            recordLabel={(record?.label ?? t("automations.record")).toLowerCase()}
            draft={dirty ? sequence() : null}
            blocked={dirty && problems.length > 0}
          />
        ) : null}
        {workflow ? <WorkflowRuns id={workflow.id} /> : null}
      </div>
    </article>
  );
}

function WorkflowRuns({ id }: { id: string }) {
  const { t } = useTranslation();
  const runs = useQuery({
    queryKey: ["workflow-runs", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/workflows/{id}/runs", { params: { path: { id } } })),
  });
  return (
    <Panel title={t("workflows.tabs.runs")} flush>
      {runs.data ? (
        <RunRows runs={runs.data} bare />
      ) : (
        <div className="px-5 py-4">
          <Spinner label={t("grid.loading")} />
        </div>
      )}
    </Panel>
  );
}

// --- timeline pieces -------------------------------------------------------------------------

function TimelineItem({ children, dot = true }: { children: ReactNode; dot?: boolean }) {
  return (
    <li className="relative">
      {dot ? (
        <span
          aria-hidden="true"
          className="absolute top-4 -left-[27px] size-3 rounded-full border-2 border-rule bg-surface"
        />
      ) : null}
      {children}
    </li>
  );
}

function AddHere({
  label,
  onAdd,
  onSplit,
}: {
  label: string;
  onAdd: () => void;
  onSplit?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <li className="flex flex-wrap gap-2">
      <Button size="sm" variant="ghost" onClick={onAdd} aria-label={label}>
        <Plus aria-hidden="true" className="size-4" strokeWidth={1.75} />
        {t("workflows.addStep")}
      </Button>
      {onSplit ? (
        <Button size="sm" variant="ghost" onClick={onSplit}>
          <Split aria-hidden="true" className="size-4" strokeWidth={1.75} />
          {t("workflows.addSplit")}
        </Button>
      ) : null}
    </li>
  );
}

function CardShell({
  title,
  lines,
  problems,
  open,
  onOpen,
  editable,
  controls,
  children,
  editorId,
}: {
  title: string;
  lines: { label: string; text: string }[];
  problems: string[];
  open: boolean;
  onOpen: (open: boolean) => void;
  editable: boolean;
  controls?: ReactNode;
  children?: ReactNode;
  editorId: string;
}) {
  const { t } = useTranslation();
  return (
    <section
      aria-label={title}
      className={`rounded-lg border bg-surface ${problems.length ? "border-danger" : "border-border"}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2 px-4 py-3">
        <div className="min-w-0 space-y-1 text-sm">
          <p className="font-semibold">{title}</p>
          {lines.map((l) => (
            <p key={l.label}>
              <span className="text-muted-foreground">{l.label}: </span>
              {l.text}
            </p>
          ))}
          {problems.length ? (
            <ul className="space-y-0.5 text-danger">
              {problems.map((p, i) => (
                <li key={i} className="flex items-center gap-1">
                  <AlertCircle aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.75} />
                  {p}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        {editable ? (
          <div className="flex items-center gap-1">
            {controls}
            <Button
              size="sm"
              variant={open ? "secondary" : "ghost"}
              aria-expanded={open}
              aria-controls={editorId}
              onClick={() => onOpen(!open)}
            >
              {open ? t("workflows.done") : t("workflows.edit")}
            </Button>
          </div>
        ) : null}
      </div>
      {open && editable ? (
        <div id={editorId} className="space-y-4 border-t border-rule px-4 py-4">
          {children}
        </div>
      ) : null}
    </section>
  );
}

function MoveControls({
  label,
  index,
  count,
  onMove,
  onDelete,
}: {
  label: string;
  index: number;
  count: number;
  onMove: (by: number) => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const icon = "size-4";
  return (
    <>
      <Button
        size="sm"
        variant="ghost"
        className="w-8 px-0"
        aria-label={t("workflows.moveUp", { step: label })}
        disabled={index === 0}
        onClick={() => onMove(-1)}
      >
        <ArrowUp aria-hidden="true" className={icon} strokeWidth={1.75} />
      </Button>
      <Button
        size="sm"
        variant="ghost"
        className="w-8 px-0"
        aria-label={t("workflows.moveDown", { step: label })}
        disabled={index === count - 1}
        onClick={() => onMove(1)}
      >
        <ArrowDown aria-hidden="true" className={icon} strokeWidth={1.75} />
      </Button>
      <Button
        size="sm"
        variant="ghost"
        className="w-8 px-0 text-muted-foreground"
        aria-label={t("workflows.delete", { step: label })}
        onClick={onDelete}
      >
        <Trash2 aria-hidden="true" className={icon} strokeWidth={1.75} />
      </Button>
    </>
  );
}

function CardItem({
  index,
  path,
  count,
  card,
  cards,
  onCards,
  schema,
  fields,
  record,
  editable,
  open,
  setOpen,
  splitsLeft,
  inPath = false,
  pathName = "",
}: {
  index: number;
  path: string;
  count: number;
  card: Card;
  cards: Card[];
  onCards: (cards: Card[]) => void;
  schema: Schema;
  fields: FieldSchema | undefined;
  record: RecordType | undefined;
  editable: boolean;
  open: string | null;
  setOpen: (path: string | null) => void;
  splitsLeft: boolean;
  inPath?: boolean;
  /** "Yes" or "No" for the cards on a split's path. */
  pathName?: string;
}) {
  const { t } = useTranslation();
  const label = inPath
    ? t("workflows.pathStep", { path: pathName, n: index + 1 })
    : t("workflows.step", { n: index + 1 });
  const replace = (next: Card) => onCards(cards.map((c, j) => (j === index ? next : c)));
  const insertAfter = (made: Card) => {
    onCards([...cards.slice(0, index + 1), made, ...cards.slice(index + 1)]);
    setOpen(inPath ? `${path.replace(/\.\d+$/, "")}.${index + 1}` : String(index + 1));
  };
  const controls = (
    <MoveControls
      label={label}
      index={index}
      count={count}
      onMove={(by) => {
        onCards(moveItem(cards, index, by));
        setOpen(null);
      }}
      onDelete={() => {
        onCards(cards.filter((_c, j) => j !== index));
        setOpen(null);
      }}
    />
  );
  const problems = cardProblems(card, schema.actions).map((p) => problemText(p, t));
  return (
    <>
      <TimelineItem dot={!inPath}>
        {card.kind === "do" ? (
          <CardShell
            title={label}
            editorId={`card-${path}`}
            lines={[
              { label: t("workflows.whenLabel"), text: describeWait(card.wait, record, t) },
              ...(card.onlyIf
                ? [
                    {
                      label: t("workflows.onlyIf"),
                      text: describeCondition(card.onlyIf, schema, fields, t),
                    },
                  ]
                : []),
              { label: t("workflows.doLabel"), text: describeActions(card.actions, schema, t) },
            ]}
            problems={problems}
            open={open === path}
            onOpen={(o) => setOpen(o ? path : null)}
            editable={editable}
            controls={controls}
          >
            <DoEditor
              card={card}
              onChange={replace}
              schema={schema}
              fields={fields}
              record={record}
            />
          </CardShell>
        ) : (
          <SplitItem
            card={card}
            path={path}
            label={label}
            onChange={replace}
            schema={schema}
            fields={fields}
            record={record}
            editable={editable}
            open={open}
            setOpen={setOpen}
            controls={controls}
            problems={problems}
          />
        )}
      </TimelineItem>
      {editable ? (
        <AddHere
          label={
            inPath
              ? t("workflows.addToAt", { path: pathName, n: index + 2 })
              : t("workflows.addAt", { n: index + 2 })
          }
          onAdd={() => insertAfter(newCard())}
          onSplit={!inPath && splitsLeft ? () => insertAfter(newSplit()) : undefined}
        />
      ) : null}
    </>
  );
}

function SplitItem({
  card,
  path,
  label,
  onChange,
  schema,
  fields,
  record,
  editable,
  open,
  setOpen,
  controls,
  problems,
}: {
  card: SplitCard;
  path: string;
  label: string;
  onChange: (c: SplitCard) => void;
  schema: Schema;
  fields: FieldSchema | undefined;
  record: RecordType | undefined;
  editable: boolean;
  open: string | null;
  setOpen: (path: string | null) => void;
  controls: ReactNode;
  problems: string[];
}) {
  const { t } = useTranslation();
  const question = describeCondition(card.question, schema, fields, t);
  return (
    <div className="space-y-3">
      <CardShell
        title={t("workflows.splitTitle", { step: label })}
        editorId={`card-${path}`}
        lines={[
          ...(card.wait
            ? [{ label: t("workflows.whenLabel"), text: describeWait(card.wait, record, t) }]
            : []),
          { label: t("workflows.ask"), text: question || t("workflows.problems.chooseQuestion") },
        ]}
        problems={problems}
        open={open === path}
        onOpen={(o) => setOpen(o ? path : null)}
        editable={editable}
        controls={controls}
      >
        <WhenEditor
          wait={card.wait}
          onChange={(wait) => onChange({ ...card, wait })}
          record={record}
        />
        <QuestionSelect
          label={t("workflows.question")}
          subject={record?.key ?? ""}
          schema={schema}
          fields={fields}
          value={card.question}
          required
          onChange={(question) => onChange({ ...card, question })}
        />
      </CardShell>
      <div className="grid gap-4 md:grid-cols-2">
        {(["yes", "no"] as const).map((arm) => {
          const cards = card[arm];
          const armPath = `${path}.${arm}`;
          return (
            <div key={arm} className="space-y-2 rounded-lg border border-dashed border-border p-3">
              <p className="text-sm font-semibold">
                {t(`workflows.${arm}`)}
                {question ? (
                  <span className="font-normal text-muted-foreground"> · {question}</span>
                ) : null}
              </p>
              <ol aria-label={t(`workflows.${arm}Path`)} className="space-y-3">
                {cards.map((c, i) => (
                  <CardItem
                    key={i}
                    index={i}
                    path={`${armPath}.${i}`}
                    count={cards.length}
                    card={c}
                    cards={cards}
                    onCards={(next) => onChange({ ...card, [arm]: next as DoCard[] })}
                    schema={schema}
                    fields={fields}
                    record={record}
                    editable={editable}
                    open={open}
                    setOpen={setOpen}
                    splitsLeft={false}
                    inPath
                    pathName={t(`workflows.${arm}`)}
                  />
                ))}
                {cards.length === 0 && editable ? (
                  <AddHere
                    label={t("workflows.addTo", { path: t(`workflows.${arm}`) })}
                    onAdd={() => {
                      onChange({ ...card, [arm]: [newCard()] });
                      setOpen(`${armPath}.0`);
                    }}
                  />
                ) : null}
                {cards.length === 0 && !editable ? (
                  <li className="text-sm text-muted-foreground">{t("workflows.nothingHere")}</li>
                ) : null}
              </ol>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground">{t("workflows.joinsAgain")}</p>
    </div>
  );
}

// --- card editors ------------------------------------------------------------------------------

function NumberField({
  label,
  value,
  onChange,
  min = 0,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  min?: number;
}) {
  return (
    <TextField
      label={label}
      type="number"
      inputMode="numeric"
      min={min}
      className="w-24 text-right"
      value={String(value)}
      onChange={(e) => onChange(Math.max(min, Number(e.target.value) || 0))}
    />
  );
}

function WhenEditor({
  wait,
  onChange,
  record,
}: {
  wait: Step | null;
  onChange: (wait: Step | null) => void;
  record: RecordType | undefined;
}) {
  const { t } = useTranslation();
  const mode = waitMode(wait);
  const setMode = (next: WaitMode) => {
    if (next === mode) return;
    if (next === "now") onChange(null);
    if (next === "after") onChange({ type: "wait", days: 1 });
    if (next === "date")
      onChange({
        type: "wait",
        until: record?.date_fields[0]?.path ?? "",
        offset_days: 0,
        at: "09:00",
      });
  };
  const name = useId();
  return (
    <fieldset className="space-y-3">
      <legend className="text-sm font-semibold">{t("workflows.whenLabel")}</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
        {(["now", "after", "date"] as const).map((m) => (
          <label key={m} className="flex items-center gap-2">
            <input
              type="radio"
              name={name}
              className="size-4"
              checked={mode === m}
              disabled={m === "date" && !record?.date_fields.length}
              onChange={() => setMode(m)}
            />
            {t(`workflows.when.mode_${m}`)}
          </label>
        ))}
      </div>
      {wait && mode === "after" ? (
        <div className="flex flex-wrap items-end gap-2">
          <NumberField
            label={t("workflows.when.howMany")}
            value={waitAmount(wait).amount}
            onChange={(n) => onChange(setWaitAmount(wait, n, waitAmount(wait).unit))}
          />
          <SelectField
            label={t("workflows.when.unit")}
            value={waitAmount(wait).unit}
            onChange={(e) =>
              onChange(setWaitAmount(wait, waitAmount(wait).amount, e.target.value as "days"))
            }
            options={(["minutes", "hours", "days"] as const).map((u) => ({
              value: u,
              label: t(`workflows.units.${u}`),
            }))}
          />
        </div>
      ) : null}
      {wait && mode === "date" ? (
        <div className="flex flex-wrap items-end gap-2">
          <NumberField
            label={t("workflows.when.howMany")}
            value={Math.abs(dateOffset(wait).amount)}
            onChange={(n) => {
              const { amount, unit } = dateOffset(wait);
              onChange(setDateOffset(wait, amount < 0 ? -n : n, unit));
            }}
          />
          <SelectField
            label={t("workflows.when.unit")}
            value={dateOffset(wait).unit}
            onChange={(e) =>
              onChange(setDateOffset(wait, dateOffset(wait).amount, e.target.value as "days"))
            }
            options={(["days", "hours"] as const).map((u) => ({
              value: u,
              label: t(`workflows.units.${u}`),
            }))}
          />
          <SelectField
            label={t("workflows.when.beforeOrAfter")}
            value={dateOffset(wait).amount < 0 ? "before" : "after"}
            onChange={(e) => {
              const { amount, unit } = dateOffset(wait);
              const size = Math.abs(amount);
              onChange(setDateOffset(wait, e.target.value === "before" ? -size : size, unit));
            }}
            options={[
              { value: "before", label: t("workflows.when.before") },
              { value: "after", label: t("workflows.when.after") },
            ]}
          />
          <SelectField
            label={t("workflows.when.date")}
            value={wait.until ?? ""}
            onChange={(e) => onChange({ ...wait, until: e.target.value })}
            options={[
              { value: "", label: "—" },
              ...(record?.date_fields ?? []).map((f) => ({ value: f.path, label: f.label })),
            ]}
          />
        </div>
      ) : null}
      {wait ? (
        <div className="space-y-2">
          <div className="flex flex-wrap items-end gap-3">
            <CheckboxField
              label={t("workflows.when.atTime")}
              checked={wait.at !== undefined}
              onChange={(e) => {
                const rest = omit(wait, "at");
                onChange(e.target.checked ? { ...rest, at: "09:00" } : rest);
              }}
            />
            {wait.at !== undefined ? (
              <TextField
                label={t("workflows.when.time")}
                type="time"
                value={wait.at}
                onChange={(e) => onChange({ ...wait, at: e.target.value })}
              />
            ) : null}
          </div>
          {(["business_day", "quiet_hours"] as const).map((flag) => (
            <CheckboxField
              key={flag}
              label={t(`workflows.when.${flag}`)}
              checked={Boolean(wait[flag])}
              onChange={(e) => {
                const rest = omit(wait, flag);
                onChange(e.target.checked ? { ...rest, [flag]: true } : rest);
              }}
            />
          ))}
        </div>
      ) : null}
    </fieldset>
  );
}

function QuestionSelect({
  label,
  subject,
  schema,
  fields,
  value,
  onChange,
  required = false,
}: {
  label: string;
  subject: string;
  schema: Schema;
  fields: FieldSchema | undefined;
  value: Condition | null;
  onChange: (c: Condition | null) => void;
  required?: boolean;
}) {
  const { t } = useTranslation();
  const keys = questionsOf(value);
  if (keys === null || keys.length > 1) {
    // An older check on fields (or several questions): shown in words, can be replaced.
    return (
      <div className="space-y-1 text-sm">
        <p className="font-semibold">{label}</p>
        <p>{describeCondition(value, schema, fields, t)}</p>
        <Button size="sm" variant="ghost" onClick={() => onChange(null)}>
          {t("workflows.replaceCheck")}
        </Button>
      </div>
    );
  }
  return (
    <SelectField
      label={label}
      value={keys[0] ?? ""}
      onChange={(e) => onChange(e.target.value ? { predicate: e.target.value } : null)}
      options={[
        { value: "", label: required ? "—" : t("workflows.always") },
        ...schema.questions
          .filter((q) => q.subject === subject)
          .map((q) => ({ value: q.key, label: q.label })),
      ]}
    />
  );
}

function DoEditor({
  card,
  onChange,
  schema,
  fields,
  record,
}: {
  card: DoCard;
  onChange: (c: DoCard) => void;
  schema: Schema;
  fields: FieldSchema | undefined;
  record: RecordType | undefined;
}) {
  const { t } = useTranslation();
  const subject = record?.key ?? "";
  const setAction = (i: number, step: Step) =>
    onChange({ ...card, actions: card.actions.map((a, j) => (j === i ? step : a)) });
  return (
    <>
      <WhenEditor
        wait={card.wait}
        onChange={(wait) => onChange({ ...card, wait })}
        record={record}
      />
      <QuestionSelect
        label={t("workflows.onlyIf")}
        subject={subject}
        schema={schema}
        fields={fields}
        value={card.onlyIf}
        onChange={(onlyIf) => onChange({ ...card, onlyIf })}
      />
      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold">{t("workflows.doLabel")}</legend>
        {card.actions.map((step, i) => (
          <div key={i} className="space-y-2 rounded-md border border-rule p-3">
            <ActionForm
              step={step}
              onChange={(s) => setAction(i, s)}
              schema={schema}
              fields={fields}
              record={record}
            />
            <Button
              size="sm"
              variant="ghost"
              className="text-muted-foreground"
              onClick={() =>
                onChange({ ...card, actions: card.actions.filter((_a, j) => j !== i) })
              }
            >
              {t("workflows.removeAction")}
            </Button>
          </div>
        ))}
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            onChange({
              ...card,
              actions: [...card.actions, { type: "action", action: "", config: {} }],
            })
          }
        >
          {card.actions.length ? t("workflows.addAnotherAction") : t("workflows.addAction")}
        </Button>
      </fieldset>
    </>
  );
}

function ActionForm({
  step,
  onChange,
  schema,
  fields,
  record,
}: {
  step: Step;
  onChange: (s: Step) => void;
  schema: Schema;
  fields: FieldSchema | undefined;
  record: RecordType | undefined;
}) {
  const { t } = useTranslation();
  const config = step.config ?? {};
  const subject = record?.key ?? "";
  const actions = schema.actions.filter(
    (a) => a.subjects.length === 0 || a.subjects.includes(subject),
  );
  const action: ActionDef | undefined = schema.actions.find((a) => a.key === step.action);
  const variables = fields?.subjects.find((s) => s.key === subject)?.fields ?? [];
  const set = (name: string, value: unknown) =>
    onChange({ ...step, config: { ...config, [name]: value } });
  return (
    <div className="space-y-2">
      <SelectField
        label={t("workflows.action")}
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
      {action?.message ? (
        <p className="text-sm">
          <Link
            to="/settings/notifications"
            search={{ edit: action.message }}
            className="font-medium underline underline-offset-2"
          >
            {t("workflows.editWording")}
          </Link>
        </p>
      ) : null}
      {action?.fields.map((f) => {
        const label = f.required ? `${f.label} *` : f.label;
        if (f.type === "multi") {
          const options = f.name === "to" ? (record?.recipients ?? f.choices) : f.choices;
          const chosen = (config[f.name] as string[] | undefined) ?? [];
          return (
            <fieldset key={f.name} className="text-sm">
              <legend className="mb-1 font-medium">{label}</legend>
              {options.map((o) => (
                <label key={o} className="mr-4 inline-flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="size-4"
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
                ...f.choices.map((c) => ({
                  value: c,
                  label: t(`workflows.choices.${c}`, { defaultValue: c }),
                })),
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
                className="w-full rounded-md border border-field bg-surface px-3 py-2 text-sm"
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
                  ...variables.map((x) => ({ value: x.path, label: x.label })),
                ]}
              />
            </div>
          );
        }
        if (f.type === "bool") {
          return (
            <CheckboxField
              key={f.name}
              label={f.label}
              checked={config[f.name] !== false}
              onChange={(e) => set(f.name, e.target.checked)}
            />
          );
        }
        if (f.type === "whatsapp_template" || f.type === "saved_reply") {
          return (
            <SavedTemplateSelect
              key={f.name}
              kind={f.type}
              label={label}
              value={String(config[f.name] ?? "")}
              onChange={(v) => set(f.name, v)}
            />
          );
        }
        if (f.type === "workflow") {
          return <WorkflowSelect key={f.name} label={label} subject={subject}
                   value={String(config[f.name] ?? "")} onChange={(v) => set(f.name, v)} />; // prettier-ignore
        }
        return (
          <TextField
            key={f.name}
            label={label}
            type={f.type === "number" ? "number" : "text"}
            value={String(config[f.name] ?? "")}
            onChange={(e) =>
              set(
                f.name,
                f.type === "number" && e.target.value !== ""
                  ? Number(e.target.value)
                  : e.target.value,
              )
            }
          />
        );
      })}
    </div>
  );
}

function WorkflowSelect({
  label,
  subject,
  value,
  onChange,
}: {
  label: string;
  subject: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const list = useQuery({
    queryKey: ["workflows"],
    queryFn: async () => unwrap(await api.GET("/api/v1/workflows")),
  });
  return (
    <SelectField
      label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      options={[
        { value: "", label: "—" },
        ...(list.data ?? [])
          .filter((w) => w.subject_type === subject)
          .map((w) => ({ value: w.id, label: w.name })),
      ]}
    />
  );
}

/** G4 actions pick an approved WhatsApp template or a saved message instead of an id. */
function SavedTemplateSelect({
  kind,
  label,
  value,
  onChange,
}: {
  kind: "whatsapp_template" | "saved_reply";
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const options = useQuery({
    queryKey: ["automation-saved-templates", kind],
    queryFn: async () => {
      if (kind === "whatsapp_template") {
        const page = unwrap(await api.GET("/api/v1/whatsapp-templates"));
        return page.results
          .filter((row) => row.status === "approved" && row.category !== "marketing")
          .map((row) => ({ value: row.id, label: row.name }));
      }
      const page = unwrap(await api.GET("/api/v1/canned-replies"));
      return page.results.map((row) => ({ value: row.id, label: row.title }));
    },
  });
  return (
    <SelectField
      label={label}
      value={value}
      hint={options.data && !options.data.length ? t("automationExtras.noneYet") : undefined}
      onChange={(e) => onChange(e.target.value)}
      options={[{ value: "", label: "—" }, ...(options.data ?? [])]}
    />
  );
}

// --- start -------------------------------------------------------------------------------------

function StartCard({
  draft,
  schema,
  fields,
  builtIn,
  editable,
  open,
  onOpen,
  onChange,
  problems,
}: {
  draft: Draft;
  schema: Schema;
  fields: FieldSchema | undefined;
  builtIn: boolean;
  editable: boolean;
  open: boolean;
  onOpen: (open: boolean) => void;
  onChange: (d: Draft) => void;
  problems: string[];
}) {
  const { t } = useTranslation();
  const subject = subjectOf(draft, schema);
  const record = schema.record_types.find((r) => r.key === subject);
  const only = describeCondition(draft.conditions, schema, fields, t);
  const stops = draft.stop_when.map((e) => eventLabel(schema, e)).join(t("workflows.or"));
  return (
    <CardShell
      title={t("workflows.startTitle")}
      editorId="card-start"
      lines={[
        { label: t("workflows.startsLabel"), text: describeStart(draft, schema, t) },
        ...(only ? [{ label: t("workflows.onlyIf"), text: only }] : []),
        ...(stops ? [{ label: t("workflows.stopWhen"), text: stops }] : []),
      ]}
      problems={problems}
      open={open}
      onOpen={onOpen}
      editable={editable}
    >
      <StartEditor draft={draft} schema={schema} builtIn={builtIn} onChange={onChange} />
      {subject ? (
        <StartChecks
          draft={draft}
          schema={schema}
          fields={fields}
          record={record}
          onChange={onChange}
        />
      ) : null}
    </CardShell>
  );
}

function StartEditor({
  draft,
  schema,
  builtIn,
  onChange,
}: {
  draft: Draft;
  schema: Schema;
  builtIn: boolean;
  onChange: (d: Draft) => void;
}) {
  const { t } = useTranslation();
  const c = draft.trigger_config;
  const setConfig = (key: string, value: unknown) =>
    onChange({ ...draft, trigger_config: { ...c, [key]: value } });
  const subject = subjectOf(draft, schema);
  const record = schema.record_types.find((r) => r.key === subject);
  const events = schema.starts.events.filter((e) => !builtIn || e.subject === subject);
  return (
    <div className="space-y-3">
      {builtIn ? null : (
        <SelectField
          label={t("workflows.startKind")}
          value={draft.trigger_type}
          onChange={(e) =>
            onChange({
              ...draft,
              trigger_type: e.target.value as StartKind,
              trigger_config: {},
              stop_when: [],
              conditions: {},
            })
          }
          options={(["event", "schedule", "date", "manual"] as const).map((k) => ({
            value: k,
            label: t(`workflows.kinds.${k}`),
          }))}
        />
      )}
      {draft.trigger_type === "event" ? (
        <SelectField
          label={t("workflows.event")}
          value={String(c.event ?? "")}
          onChange={(e) => onChange({ ...draft, trigger_config: { event: e.target.value } })}
          options={[
            { value: "", label: "—" },
            ...[...events]
              .sort((a, b) => a.label.localeCompare(b.label))
              .map((e) => ({ value: e.event, label: e.label })),
          ]}
        />
      ) : builtIn ? null : (
        <SelectField
          label={t("workflows.recordType")}
          value={String(c.subject ?? "")}
          onChange={(e) =>
            onChange({
              ...draft,
              trigger_config: { subject: e.target.value },
              stop_when: [],
              conditions: {},
            })
          }
          options={[
            { value: "", label: "—" },
            ...schema.record_types.map((r) => ({ value: r.key, label: r.label })),
          ]}
        />
      )}
      {draft.trigger_type === "schedule" ? (
        <div className="flex flex-wrap items-end gap-2">
          <SelectField
            label={t("workflows.frequency")}
            value={String(c.frequency ?? "")}
            onChange={(e) => setConfig("frequency", e.target.value)}
            options={[
              { value: "", label: "—" },
              ...schema.starts.frequencies.map((f) => ({
                value: f,
                label: t(`automations.frequencies.${f}`),
              })),
            ]}
          />
          {c.frequency === "weekly" ? (
            <SelectField
              label={t("workflows.weekday")}
              value={String(c.weekday ?? 0)}
              onChange={(e) => setConfig("weekday", Number(e.target.value))}
              options={WEEKDAYS.map((d, i) => ({
                value: String(i),
                label: t(`automations.days7.${d}`),
              }))}
            />
          ) : null}
          {c.frequency === "monthly" ? (
            <SelectField
              label={t("workflows.dayOfMonth")}
              value={String(c.day ?? 1)}
              onChange={(e) => setConfig("day", Number(e.target.value))}
              options={Array.from({ length: 28 }, (_x, i) => ({
                value: String(i + 1),
                label: String(i + 1),
              }))}
            />
          ) : null}
          <TextField
            label={t("workflows.when.time")}
            type="time"
            value={String(c.time ?? "08:00")}
            onChange={(e) => setConfig("time", e.target.value)}
          />
        </div>
      ) : null}
      {draft.trigger_type === "date" && record ? (
        <DateStartEditor draft={draft} record={record} onChange={onChange} />
      ) : null}
    </div>
  );
}

/** "14 days before the package expires, at 09:00", with up to six times. */
function DateStartEditor({
  draft,
  record,
  onChange,
}: {
  draft: Draft;
  record: RecordType;
  onChange: (d: Draft) => void;
}) {
  const { t } = useTranslation();
  const c = draft.trigger_config;
  const { values, unit } = startOffsets(c);
  const field = record.start_dates.find((d) => d.field === c.field);
  // Near a date and time the start counts in minutes; the editor shows hours.
  const shown = values.map((v) => (unit === "minutes" ? v / 60 : v));
  const write = (next: number[]) => {
    const config = { ...c };
    if (unit === "minutes") config.minutes = next.map((h) => Math.round(h * 60));
    else config.offset_days = next;
    onChange({ ...draft, trigger_config: config });
  };
  const unitLabel = unit === "minutes" ? t("workflows.units.hours") : t("workflows.units.days");
  return (
    <div className="space-y-3">
      <SelectField
        label={t("workflows.when.date")}
        value={String(c.field ?? "")}
        onChange={(e) => onChange({ ...draft, trigger_config: { ...c, field: e.target.value } })}
        options={[
          { value: "", label: "—" },
          ...record.start_dates.map((d) => ({ value: d.field, label: d.label })),
        ]}
      />
      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold">
          {t("workflows.start.times", { date: field?.label ?? "" })}
        </legend>
        {shown.map((v, i) => (
          <div key={i} className="flex flex-wrap items-end gap-2">
            <NumberField
              label={unitLabel}
              value={Math.abs(v)}
              onChange={(n) => write(shown.map((x, j) => (j === i ? (x < 0 ? -n : n) : x)))}
            />
            <SelectField
              label={t("workflows.when.beforeOrAfter")}
              value={v < 0 ? "before" : "after"}
              onChange={(e) =>
                write(
                  shown.map((x, j) =>
                    j === i ? (e.target.value === "before" ? -Math.abs(x) : Math.abs(x)) : x,
                  ),
                )
              }
              options={[
                { value: "before", label: t("workflows.when.before") },
                { value: "after", label: t("workflows.when.after") },
              ]}
            />
            {shown.length > 1 ? (
              <Button
                size="sm"
                variant="ghost"
                className="text-muted-foreground"
                onClick={() => write(shown.filter((_x, j) => j !== i))}
              >
                {t("workflows.removeTime")}
              </Button>
            ) : null}
          </div>
        ))}
        {shown.length < 6 ? (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => write([...shown, -(unit === "minutes" ? 1 : 7)])}
          >
            {t("workflows.addTime")}
          </Button>
        ) : null}
      </fieldset>
      {unit === "days" ? (
        <TextField
          label={t("workflows.when.time")}
          type="time"
          value={String(c.time ?? "08:00")}
          onChange={(e) => onChange({ ...draft, trigger_config: { ...c, time: e.target.value } })}
        />
      ) : null}
    </div>
  );
}

function StartChecks({
  draft,
  schema,
  fields,
  record,
  onChange,
}: {
  draft: Draft;
  schema: Schema;
  fields: FieldSchema | undefined;
  record: RecordType | undefined;
  onChange: (d: Draft) => void;
}) {
  const { t } = useTranslation();
  const keys = questionsOf(draft.conditions);
  const subject = record?.key ?? "";
  const stopChoices = (record?.stop_when ?? []).filter((e) => !draft.stop_when.includes(e));
  return (
    <>
      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold">{t("workflows.onlyIf")}</legend>
        {keys === null ? (
          <div className="space-y-1 text-sm">
            <p>{describeCondition(draft.conditions, schema, fields, t)}</p>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onChange({ ...draft, conditions: {} })}
            >
              {t("workflows.replaceCheck")}
            </Button>
          </div>
        ) : (
          <>
            {keys.map((k) => (
              <Chip
                key={k}
                label={questionLabel(schema, k)}
                remove={t("workflows.removeNamed", { name: questionLabel(schema, k) })}
                onRemove={() =>
                  onChange({ ...draft, conditions: fromQuestions(keys.filter((x) => x !== k)) })
                }
              />
            ))}
            <SelectField
              label={t("workflows.addQuestion")}
              value=""
              onChange={(e) =>
                e.target.value &&
                onChange({ ...draft, conditions: fromQuestions([...keys, e.target.value]) })
              }
              options={[
                { value: "", label: "—" },
                ...schema.questions
                  .filter((q) => q.subject === subject && !keys.includes(q.key))
                  .map((q) => ({ value: q.key, label: q.label })),
              ]}
            />
          </>
        )}
      </fieldset>
      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold">{t("workflows.stopWhen")}</legend>
        <p className="text-xs text-muted-foreground">{t("workflows.stopWhenHelp")}</p>
        {draft.stop_when.map((e) => (
          <Chip
            key={e}
            label={eventLabel(schema, e)}
            remove={t("workflows.removeNamed", { name: eventLabel(schema, e) })}
            onRemove={() =>
              onChange({ ...draft, stop_when: draft.stop_when.filter((x) => x !== e) })
            }
          />
        ))}
        {draft.stop_when.length < MAX_STOPS ? (
          <SelectField
            label={t("workflows.addStop")}
            value=""
            onChange={(ev) =>
              ev.target.value &&
              onChange({ ...draft, stop_when: [...draft.stop_when, ev.target.value] })
            }
            options={[
              { value: "", label: "—" },
              ...stopChoices.map((e) => ({ value: e, label: eventLabel(schema, e) })),
            ]}
          />
        ) : null}
      </fieldset>
    </>
  );
}

function Chip({
  label,
  remove,
  onRemove,
}: {
  label: string;
  remove: string;
  onRemove: () => void;
}) {
  return (
    <p className="flex items-center gap-2 text-sm">
      <span>{label}</span>
      <Button
        size="sm"
        variant="ghost"
        className="w-8 px-0 text-muted-foreground"
        aria-label={remove}
        onClick={onRemove}
      >
        <Trash2 aria-hidden="true" className="size-4" strokeWidth={1.75} />
      </Button>
    </p>
  );
}
