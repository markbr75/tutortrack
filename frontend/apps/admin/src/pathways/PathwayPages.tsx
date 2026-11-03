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
  TextAreaField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api, usePermission } from "../api";
import { RecordHeader } from "../components/RecordHeader";
import {
  allStepKeys,
  move,
  newStep,
  QUESTION_TYPES,
  uniqueKey,
  type Assignee,
  type Question,
  type Stage,
  type Step,
} from "./stages";

type Template = components["schemas"]["PathwayTemplate"];
type Schema = components["schemas"]["PathwaySchema"];
type Translate = (key: string, options?: Record<string, unknown>) => string;

const linkClass = "underline-offset-2 hover:underline";
const KINDS = ["apply", "join", "finish", "custom"] as const;
const STARTS_ON_ITS_OWN = ["apply", "join", "finish"];

function usePathwaySchema() {
  return useQuery({
    queryKey: ["pathway-schema"],
    queryFn: async () => unwrap(await api.GET("/api/v1/pathway-schema")),
    staleTime: 5 * 60_000,
  });
}

function templateContext(template: Template, t: Translate): string {
  return [
    t(`pathways.kind.${template.kind ?? "custom"}`),
    template.active ? null : t("pathways.off"),
    template.edited ? t("pathways.edited") : null,
    template.update_available ? t("pathways.newerDefault") : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function DefaultSwitch({ template }: { template: Template }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("pathway.manage");
  const toggle = useMutation({
    mutationFn: async (used: boolean) =>
      unwrap(
        await api.PATCH("/api/v1/pathway-templates/{id}", {
          params: { path: { id: template.id } },
          body: { used_by_default: used },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["pathway-templates"] }),
  });
  if (!STARTS_ON_ITS_OWN.includes(template.kind ?? "custom")) {
    return <span className="text-sm text-muted-foreground">{t("pathways.byHand")}</span>;
  }
  const used = Boolean(template.used_by_default);
  if (!canManage) {
    return (
      <span className={used ? "text-sm" : "text-sm text-muted-foreground"}>
        {used ? t("pathways.startsOnItsOwn") : t("pathways.byHand")}
      </span>
    );
  }
  return (
    <div className="flex flex-col items-end gap-1">
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4"
          checked={used}
          disabled={toggle.isPending || !template.active}
          onChange={() => toggle.mutate(!used)}
          aria-label={t("pathways.useFor", { name: template.name })}
        />
        <span className={used ? undefined : "text-muted-foreground"}>
          {t("pathways.startsOnItsOwn")}
        </span>
      </label>
      {toggle.error ? <span className="text-xs text-danger">{toggle.error.message}</span> : null}
    </div>
  );
}

/** Settings › Pathways (FR-34-2): the ready-made pathways, then the business's own. */
export function PathwaysPage() {
  const { t } = useTranslation();
  const canManage = usePermission("pathway.manage");
  const list = useQuery({
    queryKey: ["pathway-templates"],
    queryFn: async () => unwrap(await api.GET("/api/v1/pathway-templates")),
  });
  if (!list.data) return <Spinner label={t("grid.loading")} />;
  const builtins = list.data.filter((p) => p.builtin_key);
  const own = list.data.filter((p) => !p.builtin_key);
  const rows = (items: Template[]) => (
    <PanelRows>
      {items.map((p) => (
        <PanelRow key={p.id} className="hover:bg-muted/60">
          <NamePlate
            name={
              <Link to="/settings/pathways/$id" params={{ id: p.id }} className={linkClass}>
                {p.name}
              </Link>
            }
            context={templateContext(p, t)}
            aside={<DefaultSwitch template={p} />}
          />
        </PanelRow>
      ))}
    </PanelRows>
  );
  return (
    <div className="max-w-[56rem]">
      <PageHeader
        title={t("pathways.title")}
        description={t("pathways.help")}
        actions={
          canManage ? (
            <Link
              to="/settings/pathways/$id"
              params={{ id: "new" }}
              className={buttonClass({ size: "sm" })}
            >
              {t("pathways.new")}
            </Link>
          ) : null
        }
      />
      <div className="space-y-6">
        <Panel title={t("pathways.readyMade")} description={t("pathways.readyMadeHelp")} flush>
          {builtins.length ? (
            rows(builtins)
          ) : (
            <p className="px-5 py-4 text-sm text-muted-foreground">{t("pathways.noReadyMade")}</p>
          )}
        </Panel>
        <Panel title={t("pathways.yours")} flush>
          {own.length ? (
            rows(own)
          ) : (
            <p className="px-5 py-4 text-sm text-muted-foreground">{t("pathways.noOwn")}</p>
          )}
        </Panel>
      </div>
    </div>
  );
}

type Kind = (typeof KINDS)[number];

type Draft = {
  name: string;
  description: string;
  kind: Kind;
  record_type: string;
  active: boolean;
  stages: Stage[];
};

const NEW_DRAFT: Draft = {
  name: "",
  description: "",
  kind: "custom",
  record_type: "job",
  active: true,
  stages: [{ key: "stage_1", name: "", gate: "", steps: [] }],
};

function toDraft(template: Template): Draft {
  return {
    name: template.name,
    description: template.description ?? "",
    kind: template.kind ?? "custom",
    record_type: template.record_type,
    active: template.active ?? true,
    stages: (template.stages as Stage[]) ?? [],
  };
}

/** What would stop the pathway saving, in words, before it is sent. */
function problems(draft: Draft, t: Translate): string[] {
  const out: string[] = [];
  if (!draft.name.trim()) out.push(t("pathways.problem.name"));
  if (!draft.stages.length) out.push(t("pathways.problem.noStages"));
  draft.stages.forEach((stage, i) => {
    if (!stage.name.trim()) out.push(t("pathways.problem.stageName", { n: i + 1 }));
    if (!stage.steps.length) out.push(t("pathways.problem.noSteps", { n: i + 1 }));
  });
  return out;
}

export function PathwayEditorPage({ id }: { id: string }) {
  const { t } = useTranslation();
  const template = useQuery({
    queryKey: ["pathway-templates", id],
    enabled: id !== "new",
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/pathway-templates/{id}", { params: { path: { id } } })),
  });
  const schema = usePathwaySchema();
  if (!schema.data || (id !== "new" && !template.data)) {
    return <Spinner label={t("grid.loading")} />;
  }
  return (
    <Editor
      key={template.data?.updated_at ?? "new"}
      template={template.data}
      schema={schema.data}
    />
  );
}

function Editor({ template, schema }: { template?: Template; schema: Schema }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canManage = usePermission("pathway.manage");
  const [draft, setDraft] = useState<Draft>(template ? toDraft(template) : NEW_DRAFT);
  const [saved, setSaved] = useState(false);
  const set = (changes: Partial<Draft>) => {
    setSaved(false);
    setDraft((d) => ({ ...d, ...changes }));
  };
  const setStage = (index: number, stage: Stage) =>
    set({ stages: draft.stages.map((s, i) => (i === index ? stage : s)) });
  const save = useMutation({
    mutationFn: async () => {
      const body = { ...draft, stages: draft.stages as unknown };
      return template
        ? unwrap(
            await api.PATCH("/api/v1/pathway-templates/{id}", {
              params: { path: { id: template.id } },
              body,
            }),
          )
        : unwrap(await api.POST("/api/v1/pathway-templates", { body }));
    },
    onSuccess: (data) => {
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: ["pathway-templates"] });
      if (!template) void navigate({ to: "/settings/pathways/$id", params: { id: data.id } });
    },
  });
  const reset = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/pathway-templates/{id}/reset-to-default", {
          params: { path: { id: template?.id ?? "" } },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["pathway-templates"] }),
  });
  const found = problems(draft, t);
  const recordTypes = schema.record_types.map((r) => ({ value: r.key, label: r.label }));
  return (
    <article className="max-w-[48rem]">
      <RecordHeader
        back={<Link to="/settings/pathways">{t("pathways.title")}</Link>}
        title={template ? template.name : t("pathways.new")}
        description={template ? templateContext(template, t) : t("pathways.newHelp")}
        actions={
          template?.builtin_key && canManage ? (
            <Button
              size="sm"
              variant="secondary"
              disabled={reset.isPending || !template.edited}
              onClick={() => reset.mutate()}
            >
              {t("pathways.reset")}
            </Button>
          ) : null
        }
      />
      <div className="space-y-6">
        {template?.update_available ? (
          <Alert tone="info">{t("pathways.newerDefaultHelp")}</Alert>
        ) : null}
        <Panel title={t("pathways.details")}>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label={t("pathways.name")}
              value={draft.name}
              disabled={!canManage}
              onChange={(e) => set({ name: e.target.value })}
            />
            <SelectField
              label={t("pathways.kindLabel")}
              value={draft.kind}
              disabled={!canManage || Boolean(template?.builtin_key)}
              options={KINDS.map((k) => ({ value: k, label: t(`pathways.kind.${k}`) }))}
              onChange={(e) => set({ kind: e.target.value as Kind })}
            />
            <SelectField
              label={t("pathways.about")}
              hint={t("pathways.aboutHint")}
              value={draft.record_type}
              disabled={!canManage || Boolean(template)}
              options={recordTypes}
              onChange={(e) => set({ record_type: e.target.value })}
            />
            <CheckboxField
              label={t("pathways.on")}
              checked={draft.active}
              disabled={!canManage}
              onChange={(e) => set({ active: e.target.checked })}
            />
          </div>
          <div className="mt-4">
            <TextAreaField
              label={t("pathways.description")}
              rows={2}
              value={draft.description}
              disabled={!canManage}
              onChange={(e) => set({ description: e.target.value })}
            />
          </div>
        </Panel>
        {draft.stages.map((stage, index) => (
          <StageEditor
            key={stage.key}
            index={index}
            count={draft.stages.length}
            stage={stage}
            draft={draft}
            schema={schema}
            readOnly={!canManage}
            onChange={(next) => setStage(index, next)}
            onMove={(by) => set({ stages: move(draft.stages, index, by) })}
            onRemove={() => set({ stages: draft.stages.filter((_, i) => i !== index) })}
          />
        ))}
        {canManage ? (
          <Panel
            footer={
              <>
                <Button disabled={save.isPending || found.length > 0} onClick={() => save.mutate()}>
                  {t("common.save")}
                </Button>
                {saved ? <span className="text-sm text-success">{t("pathways.saved")}</span> : null}
              </>
            }
          >
            <div className="space-y-3">
              <Button
                variant="secondary"
                size="sm"
                onClick={() =>
                  set({
                    stages: [
                      ...draft.stages,
                      {
                        key: uniqueKey(
                          "stage",
                          draft.stages.map((s) => s.key),
                        ),
                        name: "",
                        gate: "",
                        steps: [],
                      },
                    ],
                  })
                }
              >
                <Plus aria-hidden="true" className="size-4" />
                {t("pathways.addStage")}
              </Button>
              {found.length ? (
                <Alert tone="warning" title={t("pathways.problem.title")}>
                  <ul className="list-disc pl-5">
                    {found.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                </Alert>
              ) : null}
              {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
              {reset.error ? <Alert tone="danger">{reset.error.message}</Alert> : null}
            </div>
          </Panel>
        ) : null}
      </div>
    </article>
  );
}

function MoveButtons({
  index,
  count,
  label,
  onMove,
  onRemove,
}: {
  index: number;
  count: number;
  label: string;
  onMove: (by: -1 | 1) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  return (
    <span className="flex items-center gap-1">
      <Button
        size="sm"
        variant="ghost"
        disabled={index === 0}
        aria-label={t("pathways.moveUp", { name: label })}
        onClick={() => onMove(-1)}
      >
        <ArrowUp aria-hidden="true" className="size-4" />
      </Button>
      <Button
        size="sm"
        variant="ghost"
        disabled={index === count - 1}
        aria-label={t("pathways.moveDown", { name: label })}
        onClick={() => onMove(1)}
      >
        <ArrowDown aria-hidden="true" className="size-4" />
      </Button>
      <Button
        size="sm"
        variant="ghost"
        aria-label={t("pathways.remove", { name: label })}
        onClick={onRemove}
      >
        <Trash2 aria-hidden="true" className="size-4" />
      </Button>
    </span>
  );
}

function StageEditor({
  index,
  count,
  stage,
  draft,
  schema,
  readOnly,
  onChange,
  onMove,
  onRemove,
}: {
  index: number;
  count: number;
  stage: Stage;
  draft: Draft;
  schema: Schema;
  readOnly: boolean;
  onChange: (stage: Stage) => void;
  onMove: (by: -1 | 1) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState("");
  const label = stage.name || t("pathways.stageN", { n: index + 1 });
  const types = schema.step_types.map((s) => ({ value: s.key, label: s.label }));
  const setStep = (i: number, step: Step) =>
    onChange({ ...stage, steps: stage.steps.map((s, j) => (j === i ? step : s)) });
  return (
    <Panel
      title={t("pathways.stageTitle", { n: index + 1, name: stage.name || "…" })}
      aside={
        readOnly ? undefined : (
          <MoveButtons
            index={index}
            count={count}
            label={label}
            onMove={onMove}
            onRemove={onRemove}
          />
        )
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label={t("pathways.stageName")}
          value={stage.name}
          disabled={readOnly}
          onChange={(e) => onChange({ ...stage, name: e.target.value })}
        />
        <TextField
          label={t("pathways.gate")}
          hint={t("pathways.gateHint")}
          value={stage.gate ?? ""}
          disabled={readOnly}
          onChange={(e) =>
            onChange({ ...stage, gate: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "") })
          }
        />
      </div>
      <ol className="mt-4 space-y-3">
        {stage.steps.map((step, i) => (
          <li key={step.key} className="rounded-md border border-rule p-4">
            <StepEditor
              step={step}
              schema={schema}
              recordType={draft.record_type}
              readOnly={readOnly}
              onChange={(next) => setStep(i, next)}
              controls={
                readOnly ? null : (
                  <MoveButtons
                    index={i}
                    count={stage.steps.length}
                    label={step.name || t(`pathways.stepType.${step.type}`)}
                    onMove={(by) => onChange({ ...stage, steps: move(stage.steps, i, by) })}
                    onRemove={() =>
                      onChange({ ...stage, steps: stage.steps.filter((_, j) => j !== i) })
                    }
                  />
                )
              }
            />
          </li>
        ))}
      </ol>
      {readOnly ? null : (
        <div className="mt-4 flex flex-wrap items-end gap-2">
          <SelectField
            size="sm"
            label={t("pathways.addStepType")}
            value={adding}
            options={[{ value: "", label: t("pathways.chooseType") }, ...types]}
            onChange={(e) => setAdding(e.target.value)}
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={!adding}
            onClick={() => {
              const kind = schema.step_types.find((s) => s.key === adding);
              if (!kind) return;
              const step = newStep(
                kind.key,
                (kind.assignees[0] ?? "participant") as Assignee,
                allStepKeys(draft.stages),
              );
              onChange({ ...stage, steps: [...stage.steps, step] });
              setAdding("");
            }}
          >
            <Plus aria-hidden="true" className="size-4" />
            {t("pathways.addStep")}
          </Button>
        </div>
      )}
    </Panel>
  );
}

function StepEditor({
  step,
  schema,
  recordType,
  readOnly,
  onChange,
  controls,
}: {
  step: Step;
  schema: Schema;
  recordType: string;
  readOnly: boolean;
  onChange: (step: Step) => void;
  controls: React.ReactNode;
}) {
  const { t } = useTranslation();
  const kind = schema.step_types.find((s) => s.key === step.type);
  const assignees = kind?.assignees ?? ["participant"];
  const assignee = step.assignee ?? (assignees[0] as Assignee);
  const config = step.config ?? {};
  const setConfig = (changes: Record<string, unknown>) =>
    onChange({ ...step, config: { ...config, ...changes } });
  const text = (key: string, label: string, opts: { area?: boolean; hint?: string } = {}) =>
    opts.area ? (
      <TextAreaField
        label={label}
        rows={4}
        hint={opts.hint}
        value={String(config[key] ?? "")}
        disabled={readOnly}
        onChange={(e) => setConfig({ [key]: e.target.value })}
      />
    ) : (
      <TextField
        label={label}
        hint={opts.hint}
        value={String(config[key] ?? "")}
        disabled={readOnly}
        onChange={(e) => setConfig({ [key]: e.target.value })}
      />
    );
  const number = (key: string, label: string, min: number, max: number) => (
    <TextField
      label={label}
      type="number"
      min={min}
      max={max}
      className="tabular-nums"
      value={String(config[key] ?? "")}
      disabled={readOnly}
      onChange={(e) => setConfig({ [key]: e.target.value ? Number(e.target.value) : "" })}
    />
  );
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium">
          {kind?.label ?? step.type}
          <span className="font-normal text-muted-foreground">
            {" · "}
            {t(`pathways.assignee.${assignee}`)}
          </span>
        </p>
        {controls}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label={t("pathways.stepName")}
          value={step.name}
          placeholder={kind?.label}
          disabled={readOnly}
          onChange={(e) => onChange({ ...step, name: e.target.value })}
        />
        {assignee === "system" ? null : (
          <TextField
            label={t("pathways.dueDays")}
            hint={t("pathways.dueDaysHint")}
            type="number"
            min={1}
            max={365}
            className="tabular-nums"
            value={step.due_days ? String(step.due_days) : ""}
            disabled={readOnly}
            onChange={(e) =>
              onChange({ ...step, due_days: e.target.value ? Number(e.target.value) : null })
            }
          />
        )}
        {assignees.length > 1 ? (
          <SelectField
            label={t("pathways.who")}
            value={assignee}
            disabled={readOnly}
            options={assignees.map((a) => ({ value: a, label: t(`pathways.assignee.${a}`) }))}
            onChange={(e) => onChange({ ...step, assignee: e.target.value as Assignee })}
          />
        ) : null}
        {assignee === "staff" ? (
          <SelectField
            label={t("pathways.role")}
            value={step.role ?? ""}
            disabled={readOnly}
            options={[
              { value: "", label: t("pathways.anyStaff") },
              ...schema.roles.map((r) => ({ value: r, label: t(`pathways.roles.${r}`) })),
            ]}
            onChange={(e) => onChange({ ...step, role: e.target.value })}
          />
        ) : null}
      </div>
      {step.type === "questions" ? (
        <QuestionsEditor
          fields={(config.fields as Question[]) ?? []}
          review={Boolean(config.review)}
          readOnly={readOnly}
          onChange={(fields, review) => setConfig({ fields, review })}
        />
      ) : null}
      {step.type === "upload" ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            {text("instructions", t("pathways.cfg.instructions"), { area: true })}
          </div>
          {number("max_files", t("pathways.cfg.maxFiles"), 1, 10)}
          <CheckboxField
            label={t("pathways.cfg.verify")}
            checked={config.verify !== false}
            disabled={readOnly}
            onChange={(e) => setConfig({ verify: e.target.checked })}
          />
        </div>
      ) : null}
      {step.type === "sign" ? (
        <div className="space-y-4">
          {text("title", t("pathways.cfg.title"))}
          {text("text", t("pathways.cfg.agreement"), { area: true })}
        </div>
      ) : null}
      {step.type === "acknowledge" ? (
        <div className="space-y-4">
          {text("title", t("pathways.cfg.title"))}
          {text("text", t("pathways.cfg.toRead"), { area: true })}
          {text("link", t("pathways.cfg.link"), { hint: t("pathways.cfg.linkHint") })}
        </div>
      ) : null}
      {step.type === "staff_review" ? text("question", t("pathways.cfg.question")) : null}
      {step.type === "system_check" ? (
        <SelectField
          label={t("pathways.cfg.check")}
          value={String(config.question ?? "")}
          disabled={readOnly}
          options={[
            { value: "", label: t("pathways.chooseQuestion") },
            ...schema.questions
              .filter((q) => q.record_type === recordType)
              .map((q) => ({ value: q.key, label: q.label })),
          ]}
          onChange={(e) => setConfig({ question: e.target.value })}
        />
      ) : null}
      {step.type === "show_check" ? (
        <SelectField
          label={t("pathways.cfg.requirement")}
          value={String(config.requirement ?? "")}
          disabled={readOnly}
          options={[
            { value: "", label: t("pathways.cfg.allChecks") },
            ...schema.requirements.map((r) => ({ value: r.key, label: r.name })),
          ]}
          onChange={(e) => setConfig({ requirement: e.target.value })}
        />
      ) : null}
      {step.type === "book_call" ? (
        <div className="grid gap-4 sm:grid-cols-3">
          {text("title", t("pathways.cfg.callTitle"))}
          {number("minutes", t("pathways.cfg.minutes"), 15, 120)}
          {number("days", t("pathways.cfg.days"), 1, 28)}
        </div>
      ) : null}
      {["trial_lesson", "family_chooses"].includes(step.type) ? (
        <p className="text-sm text-muted-foreground">{t(`pathways.cfg.${step.type}`)}</p>
      ) : null}
    </div>
  );
}

function QuestionsEditor({
  fields,
  review,
  readOnly,
  onChange,
}: {
  fields: Question[];
  review: boolean;
  readOnly: boolean;
  onChange: (fields: Question[], review: boolean) => void;
}) {
  const { t } = useTranslation();
  const setField = (i: number, changes: Partial<Question>) =>
    onChange(
      fields.map((f, j) => (j === i ? { ...f, ...changes } : f)),
      review,
    );
  return (
    <fieldset className="space-y-3">
      <legend className="text-sm font-medium">{t("pathways.cfg.questions")}</legend>
      {fields.map((field, i) => (
        <div key={field.key} className="grid items-end gap-3 sm:grid-cols-[1fr_10rem_auto]">
          <TextField
            label={t("pathways.cfg.questionN", { n: i + 1 })}
            value={field.label}
            disabled={readOnly}
            onChange={(e) => setField(i, { label: e.target.value })}
          />
          <SelectField
            label={t("pathways.cfg.answerType")}
            value={field.type}
            disabled={readOnly}
            options={QUESTION_TYPES.map((q) => ({ value: q, label: t(`pathways.qType.${q}`) }))}
            onChange={(e) => setField(i, { type: e.target.value })}
          />
          <div className="flex items-center gap-2 pb-2">
            <CheckboxField
              label={t("pathways.cfg.required")}
              checked={Boolean(field.required)}
              disabled={readOnly}
              onChange={(e) => setField(i, { required: e.target.checked })}
            />
            {readOnly ? null : (
              <Button
                size="sm"
                variant="ghost"
                disabled={fields.length === 1}
                aria-label={t("pathways.remove", {
                  name: field.label || t("pathways.cfg.questionN", { n: i + 1 }),
                })}
                onClick={() =>
                  onChange(
                    fields.filter((_, j) => j !== i),
                    review,
                  )
                }
              >
                <Trash2 aria-hidden="true" className="size-4" />
              </Button>
            )}
          </div>
          {field.type === "select" || field.type === "multiselect" ? (
            <div className="sm:col-span-3">
              <TextField
                label={t("pathways.cfg.options")}
                hint={t("pathways.cfg.optionsHint")}
                value={(field.options ?? []).join(", ")}
                disabled={readOnly}
                onChange={(e) =>
                  setField(i, {
                    options: e.target.value
                      .split(",")
                      .map((o) => o.trim())
                      .filter(Boolean),
                  })
                }
              />
            </div>
          ) : null}
        </div>
      ))}
      {readOnly ? null : (
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            onChange(
              [
                ...fields,
                {
                  key: uniqueKey(
                    "question",
                    fields.map((f) => f.key),
                  ),
                  label: "",
                  type: "text",
                  required: false,
                },
              ],
              review,
            )
          }
        >
          <Plus aria-hidden="true" className="size-4" />
          {t("pathways.cfg.addQuestion")}
        </Button>
      )}
      <CheckboxField
        label={t("pathways.cfg.review")}
        checked={review}
        disabled={readOnly}
        onChange={(e) => onChange(fields, e.target.checked)}
      />
    </fieldset>
  );
}
