import { ApiError, unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { PanelEmpty, PanelLoading } from "../billing/moneyUi";
import { RecordLayout } from "../components/RecordHeader";
import { ReportsPage, ResultPanel, ScheduleForm } from "./ReportingPages";

type Dataset = components["schemas"]["BuilderDataset"];
type Dimension = components["schemas"]["BuilderDimension"];
type Saved = components["schemas"]["CustomReport"];
type Op = components["schemas"]["OpEnum"];
type Filter = { field: string; op: Op; value: string };

const PRESETS = [
  "this_month",
  "last_month",
  "this_quarter",
  "last_quarter",
  "this_year",
  "last_year",
  "last_30_days",
  "last_90_days",
  "last_12_months",
  "all",
  "custom",
] as const;
const CHARTS = ["table", "bar", "line", "pie"] as const;

interface Definition {
  dataset: string;
  group_by: string[];
  measures: string[];
  filters: Filter[];
  period: string;
  from_date: string;
  to_date: string;
  ordering: string;
  limit: number;
  chart: (typeof CHARTS)[number];
  currency: string;
}

const EMPTY: Definition = {
  dataset: "",
  group_by: [],
  measures: [],
  filters: [],
  period: "this_month",
  from_date: "",
  to_date: "",
  ordering: "",
  limit: 200,
  chart: "table",
  currency: "",
};

/** A filter value as the API wants it: lists for "in", booleans, numbers or text. */
function filterValue(dim: Dimension | undefined, f: Filter): unknown {
  if (f.op === "empty" || f.op === "not_empty") return null;
  if (f.op === "in")
    return f.value
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
  if (dim?.type === "bool") return f.value === "true";
  return f.value;
}

function toRequest(def: Definition, dataset?: Dataset) {
  const dims = new Map((dataset?.dimensions ?? []).map((d) => [d.key, d]));
  return {
    dataset: def.dataset,
    group_by: def.group_by,
    measures: def.measures,
    filters: def.filters
      .filter((f) => f.field)
      .map((f) => ({ field: f.field, op: f.op, value: filterValue(dims.get(f.field), f) })),
    period: def.period,
    from_date: def.period === "custom" && def.from_date ? def.from_date : null,
    to_date: def.period === "custom" && def.to_date ? def.to_date : null,
    ordering: def.ordering,
    limit: def.limit,
    chart: def.chart,
    currency: def.currency,
  };
}

/** A saved definition (``from``/``to``, filter values as given) back into the form. */
function fromSaved(raw: Record<string, unknown>): Definition {
  const filters = Array.isArray(raw.filters) ? (raw.filters as Record<string, unknown>[]) : [];
  return {
    ...EMPTY,
    dataset: String(raw.dataset ?? ""),
    group_by: Array.isArray(raw.group_by) ? raw.group_by.map(String) : [],
    measures: Array.isArray(raw.measures) ? raw.measures.map(String) : [],
    filters: filters.map((f) => ({
      field: String(f.field ?? ""),
      op: String(f.op ?? "eq") as Op,
      value: Array.isArray(f.value) ? f.value.join(", ") : String(f.value ?? ""),
    })),
    period: String(raw.period ?? "this_month"),
    from_date: String(raw.from ?? ""),
    to_date: String(raw.to ?? ""),
    ordering: String(raw.ordering ?? ""),
    limit: Number(raw.limit ?? 200),
    chart: (CHARTS as readonly string[]).includes(String(raw.chart))
      ? (raw.chart as Definition["chart"])
      : "table",
    currency: String(raw.currency ?? ""),
  };
}

/** A part of the definition form: a legend at 500 over its controls, ruled off from the next. */
function Section({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <fieldset className="min-w-0 border-t border-rule px-5 py-4 first:border-t-0">
      <legend className="float-left mb-2 w-full text-sm font-medium">{legend}</legend>
      <div className="clear-left space-y-3">{children}</div>
    </fieldset>
  );
}

function GroupByPicker({
  dataset,
  value,
  onChange,
}: {
  dataset: Dataset;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const { t } = useTranslation();
  const [dim, setDim] = useState("");
  const [grain, setGrain] = useState("month");
  const selected = dataset.dimensions.find((d) => d.key === dim);
  return (
    <Section legend={t("reportBuilder.columns")}>
      {value.length ? (
        <ol className="flex flex-wrap gap-2">
          {value.map((key) => {
            const [base, g] = key.split(":");
            const d = dataset.dimensions.find((x) => x.key === base);
            const label = `${d?.label ?? base}${g ? ` (${t(`reportBuilder.grains.${g}`)})` : ""}`;
            return (
              <li
                key={key}
                className="flex h-8 items-center gap-1 rounded-md border border-border bg-surface pl-2.5 text-sm"
              >
                {label}
                <button
                  type="button"
                  className="grid size-8 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                  aria-label={t("reportBuilder.removeColumn", { name: label })}
                  onClick={() => onChange(value.filter((v) => v !== key))}
                >
                  <X aria-hidden="true" className="size-3.5" strokeWidth={1.75} />
                </button>
              </li>
            );
          })}
        </ol>
      ) : null}
      {value.length < 3 ? (
        <div className="flex flex-wrap items-start gap-2">
          <SelectField
            size="sm"
            hideLabel
            label={t("reportBuilder.addColumn")}
            value={dim}
            onChange={(e) => setDim(e.target.value)}
            options={[
              { value: "", label: t("designS9a.chooseColumn") },
              ...dataset.dimensions.map((d) => ({ value: d.key, label: d.label })),
            ]}
          />
          {selected?.type === "date" ? (
            <SelectField
              size="sm"
              hideLabel
              label={t("reportBuilder.grain")}
              value={grain}
              onChange={(e) => setGrain(e.target.value)}
              options={selected.grains.map((g) => ({
                value: g,
                label: t("designS9a.byGrain", { grain: t(`reportBuilder.grains.${g}`) }),
              }))}
            />
          ) : null}
          <Button
            size="sm"
            variant="secondary"
            className="h-9"
            disabled={!dim}
            onClick={() => {
              const key = selected?.type === "date" ? `${dim}:${grain}` : dim;
              if (!value.includes(key)) onChange([...value, key]);
              setDim("");
            }}
          >
            {t("reportBuilder.add")}
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{t("reportBuilder.maxColumns")}</p>
      )}
    </Section>
  );
}

function FilterRows({
  dataset,
  filters,
  onChange,
}: {
  dataset: Dataset;
  filters: Filter[];
  onChange: (filters: Filter[]) => void;
}) {
  const { t } = useTranslation();
  const set = (i: number, patch: Partial<Filter>) =>
    onChange(filters.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  return (
    <Section legend={t("reportBuilder.filters")}>
      {filters.map((f, i) => {
        const dim = dataset.dimensions.find((d) => d.key === f.field);
        const ops = (dim?.operators ?? ["eq"]) as Op[];
        return (
          <div
            key={i}
            role="group"
            aria-label={t("reportBuilder.filterN", { n: i + 1 })}
            className="flex flex-wrap items-start gap-2"
          >
            <SelectField
              size="sm"
              hideLabel
              label={t("reportBuilder.field")}
              value={f.field}
              onChange={(e) => set(i, { field: e.target.value, op: "eq", value: "" })}
              options={[
                { value: "", label: t("designS9a.chooseColumn") },
                ...dataset.dimensions.map((d) => ({ value: d.key, label: d.label })),
              ]}
            />
            <SelectField
              size="sm"
              hideLabel
              label={t("reportBuilder.operator")}
              value={f.op}
              onChange={(e) => set(i, { op: e.target.value as Op })}
              options={ops.map((op) => ({ value: op, label: t(`reportBuilder.ops.${op}`) }))}
            />
            {f.op === "empty" || f.op === "not_empty" ? null : dim?.choices.length &&
              f.op !== "in" ? (
              <SelectField
                size="sm"
                hideLabel
                label={t("reportBuilder.value")}
                value={f.value}
                onChange={(e) => set(i, { value: e.target.value })}
                options={[
                  { value: "", label: t("designS9a.chooseValue") },
                  ...dim.choices.map((c) => ({ value: c.value, label: c.label })),
                ]}
              />
            ) : dim?.type === "bool" ? (
              <SelectField
                size="sm"
                hideLabel
                label={t("reportBuilder.value")}
                value={f.value}
                onChange={(e) => set(i, { value: e.target.value })}
                options={[
                  { value: "true", label: t("reportBuilder.yes") },
                  { value: "false", label: t("reportBuilder.no") },
                ]}
              />
            ) : (
              <TextField
                size="sm"
                hideLabel
                label={t("reportBuilder.value")}
                placeholder={
                  f.op === "in" ? t("reportBuilder.commaHint") : t("reportBuilder.value")
                }
                type={dim?.type === "date" && f.op !== "in" ? "date" : "text"}
                value={f.value}
                onChange={(e) => set(i, { value: e.target.value })}
              />
            )}
            <Button
              size="sm"
              variant="ghost"
              className="h-9 text-muted-foreground"
              aria-label={t("reportBuilder.removeFilter", { n: i + 1 })}
              onClick={() => onChange(filters.filter((_f, j) => j !== i))}
            >
              {t("reportBuilder.remove")}
            </Button>
          </div>
        );
      })}
      {filters.length < 10 ? (
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onChange([...filters, { field: "", op: "eq", value: "" }])}
        >
          {t("reportBuilder.addFilter")}
        </Button>
      ) : null}
    </Section>
  );
}

function saveBlob(blob: Blob, response: Response, fallback: string) {
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallback;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

/** E26-T08: build a report from a whitelisted dataset, run it, chart it, save, share and
 * export it. Saved custom reports are listed beside the builder. */
export function BuilderPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canExport = usePermission("reporting.export");
  const canSchedule = usePermission("reporting.schedule.manage");
  const [scheduling, setScheduling] = useState<string | null>(null);
  const [scheduledName, setScheduled] = useState("");
  const [def, setDef] = useState<Definition>(EMPTY);
  const [current, setCurrent] = useState<Saved | null>(null);
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const datasets = useQuery({
    queryKey: ["builder", "datasets"],
    queryFn: async () => unwrap(await api.GET("/api/v1/reporting/builder/datasets")),
  });
  const saved = useQuery({
    queryKey: ["custom-reports"],
    queryFn: async () => unwrap(await api.GET("/api/v1/custom-reports")),
  });
  const dataset = datasets.data?.find((d) => d.key === def.dataset);
  useEffect(() => {
    if (!def.dataset && datasets.data?.length) {
      const first = datasets.data[0]!;
      setDef({
        ...EMPTY,
        dataset: first.key,
        measures: first.measures.slice(0, 1).map((m) => m.key),
      });
    }
  }, [datasets.data, def.dataset]);
  const run = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/reporting/builder/run", { body: toRequest(def, dataset) })),
  });
  const save = useMutation({
    mutationFn: async () => {
      const body = { name, description: "", definition: toRequest(def, dataset), shared };
      return current?.is_mine
        ? unwrap(
            await api.PATCH("/api/v1/custom-reports/{id}", {
              params: { path: { id: current.id } },
              body,
            }),
          )
        : unwrap(await api.POST("/api/v1/custom-reports", { body }));
    },
    onSuccess: (report) => {
      setCurrent(report);
      void queryClient.invalidateQueries({ queryKey: ["custom-reports"] });
    },
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/custom-reports/{id}", { params: { path: { id } } })),
    onSuccess: () => {
      setCurrent(null);
      void queryClient.invalidateQueries({ queryKey: ["custom-reports"] });
    },
  });
  const exportFile = useMutation({
    mutationFn: async (fmt: "csv" | "xlsx" | "pdf") => {
      const result = await api.POST("/api/v1/reporting/builder/export", {
        body: { definition: toRequest(def, dataset), file_format: fmt, name },
        parseAs: "blob",
      });
      const response = result.response as Response;
      if (!response.ok || !result.data) throw new Error(t("reportBuilder.exportFailed"));
      saveBlob(result.data as unknown as Blob, response, `custom-report.${fmt}`);
    },
  });
  const open = (report: Saved) => {
    setCurrent(report);
    setName(report.name);
    setShared(Boolean(report.shared));
    setDef(fromSaved(report.definition));
    run.reset();
  };
  const errors = fieldErrors(run.error ?? save.error);
  const runError =
    run.error instanceof ApiError && run.error.status === 403
      ? t("reportBuilder.forbidden")
      : run.error?.message;
  const title = name || dataset?.label || "";
  const savedRows = saved.data?.results ?? [];
  return (
    <ReportsPage title={t("reportBuilder.title")} description={t("reportBuilder.intro")}>
      {datasets.data?.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("reportBuilder.noDatasets")}</p>
      ) : null}
      <RecordLayout
        main={
          datasets.isPending ? (
            <RuledPanel label={t("reportBuilder.form")} flush>
              <PanelLoading label={t("grid.loading")} />
            </RuledPanel>
          ) : dataset ? (
            <form
              aria-label={t("reportBuilder.form")}
              onSubmit={(e) => {
                e.preventDefault();
                run.mutate();
              }}
            >
              <RuledPanel title={t("reportBuilder.form")} flush>
                <div className="px-5 py-4 sm:max-w-md">
                  <SelectField
                    label={t("reportBuilder.dataset")}
                    hint={dataset.description}
                    value={def.dataset}
                    onChange={(e) => {
                      const next = datasets.data?.find((d) => d.key === e.target.value);
                      setDef({
                        ...EMPTY,
                        dataset: e.target.value,
                        measures: next ? next.measures.slice(0, 1).map((m) => m.key) : [],
                      });
                      setCurrent(null);
                    }}
                    options={(datasets.data ?? []).map((d) => ({
                      value: d.key,
                      label: `${d.label} (${d.category_label})`,
                    }))}
                  />
                </div>
                <div className="border-t border-rule">
                  <GroupByPicker
                    dataset={dataset}
                    value={def.group_by}
                    onChange={(group_by) => setDef({ ...def, group_by })}
                  />
                </div>
                <div className="border-t border-rule">
                  <Section legend={t("reportBuilder.measures")}>
                    <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
                      {dataset.measures.map((m) => (
                        <label key={m.key} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={def.measures.includes(m.key)}
                            onChange={(e) =>
                              setDef({
                                ...def,
                                measures: e.target.checked
                                  ? [...def.measures, m.key]
                                  : def.measures.filter((x) => x !== m.key),
                              })
                            }
                          />
                          {m.label}
                        </label>
                      ))}
                    </div>
                    <p className="text-xs text-muted-foreground">{t("reportBuilder.listHint")}</p>
                  </Section>
                </div>
                <div className="border-t border-rule">
                  <FilterRows
                    dataset={dataset}
                    filters={def.filters}
                    onChange={(filters) => setDef({ ...def, filters })}
                  />
                </div>
                <div className="grid items-start gap-x-4 gap-y-3 border-t border-rule px-5 py-4 sm:grid-cols-2 xl:grid-cols-3">
                  <SelectField
                    label={t("reportBuilder.period")}
                    value={def.period}
                    onChange={(e) => setDef({ ...def, period: e.target.value })}
                    options={PRESETS.map((p) => ({
                      value: p,
                      label: p === "all" ? t("reportBuilder.allTime") : t(`reporting.periods.${p}`),
                    }))}
                  />
                  {def.period === "custom" ? (
                    <>
                      <TextField
                        label={t("reportBuilder.from")}
                        type="date"
                        value={def.from_date}
                        onChange={(e) => setDef({ ...def, from_date: e.target.value })}
                      />
                      <TextField
                        label={t("reportBuilder.to")}
                        type="date"
                        value={def.to_date}
                        onChange={(e) => setDef({ ...def, to_date: e.target.value })}
                      />
                    </>
                  ) : null}
                  <SelectField
                    label={t("reportBuilder.chart")}
                    value={def.chart}
                    onChange={(e) =>
                      setDef({ ...def, chart: e.target.value as Definition["chart"] })
                    }
                    options={CHARTS.map((c) => ({
                      value: c,
                      label: t(`reportBuilder.charts.${c}`),
                    }))}
                  />
                  <SelectField
                    label={t("reportBuilder.sortBy")}
                    value={def.ordering}
                    onChange={(e) => setDef({ ...def, ordering: e.target.value })}
                    options={[
                      { value: "", label: t("reportBuilder.defaultOrder") },
                      ...[...def.group_by, ...def.measures].flatMap((key) => {
                        const label =
                          dataset.measures.find((m) => m.key === key)?.label ??
                          dataset.dimensions.find((d) => d.key === key.split(":")[0])?.label ??
                          key;
                        return [
                          { value: key, label: t("reportBuilder.ascending", { name: label }) },
                          {
                            value: `-${key}`,
                            label: t("reportBuilder.descending", { name: label }),
                          },
                        ];
                      }),
                    ]}
                  />
                  <TextField
                    label={t("reportBuilder.limit")}
                    type="number"
                    min={1}
                    max={1000}
                    className="w-24 text-right tabular-nums"
                    value={String(def.limit)}
                    onChange={(e) => setDef({ ...def, limit: Number(e.target.value) || 200 })}
                  />
                  <TextField
                    label={t("reporting.currency")}
                    hint={t("reporting.currencyHint")}
                    maxLength={3}
                    className="w-24"
                    value={def.currency}
                    onChange={(e) => setDef({ ...def, currency: e.target.value.toUpperCase() })}
                  />
                </div>
                {Object.keys(errors).length || runError ? (
                  <div className="px-5 pb-4">
                    {Object.keys(errors).length ? (
                      <Alert tone="danger" title={t("reportBuilder.invalid")}>
                        {Object.values(errors).join(" ")}
                      </Alert>
                    ) : (
                      <Alert tone="danger">{runError}</Alert>
                    )}
                  </div>
                ) : null}
                <PanelFooter>
                  <Button type="submit" loading={run.isPending}>
                    {t("reportBuilder.run")}
                  </Button>
                </PanelFooter>
              </RuledPanel>
            </form>
          ) : null
        }
        side={
          <RuledPanel
            title={t("reportBuilder.saved")}
            titleId="custom-saved"
            flush
            className="lg:sticky lg:top-20"
          >
            {scheduledName ? (
              <p role="status" className="border-b border-rule px-5 py-2.5 text-sm text-success">
                {t("reportingG5.scheduled", { name: scheduledName })}
              </p>
            ) : null}
            {saved.isPending ? (
              <PanelLoading label={t("grid.loading")} />
            ) : savedRows.length ? (
              <PanelRows>
                {savedRows.map((r) => (
                  <PanelRow key={r.id}>
                    <button
                      type="button"
                      className="text-left font-medium hover:underline"
                      aria-current={current?.id === r.id ? "true" : undefined}
                      onClick={() => open(r)}
                    >
                      {r.name}
                    </button>
                    <p className="text-xs text-muted-foreground">
                      {r.is_mine
                        ? r.shared
                          ? t("reportBuilder.sharedByYou")
                          : t("reportBuilder.private")
                        : t("reportBuilder.sharedBy", { name: r.owner_name })}
                    </p>
                    {r.is_mine ? (
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        {canSchedule && canExport ? (
                          <Button
                            variant="secondary"
                            size="sm"
                            aria-expanded={scheduling === r.id}
                            aria-label={t("reportingG5.scheduleNamed", { name: r.name })}
                            onClick={() => setScheduling(scheduling === r.id ? null : r.id)}
                          >
                            {t("reporting.scheduleEmail")}
                          </Button>
                        ) : null}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-muted-foreground"
                          aria-label={t("reportBuilder.deleteNamed", { name: r.name })}
                          onClick={() => remove.mutate(r.id)}
                        >
                          {t("reportBuilder.delete")}
                        </Button>
                      </div>
                    ) : null}
                    {scheduling === r.id ? (
                      <ScheduleForm
                        narrow
                        saved={{ id: r.id, name: r.name, kind: "custom" }}
                        onCancel={() => setScheduling(null)}
                        onDone={() => {
                          setScheduling(null);
                          setScheduled(r.name);
                          void queryClient.invalidateQueries({ queryKey: ["scheduled-reports"] });
                        }}
                      />
                    ) : null}
                  </PanelRow>
                ))}
              </PanelRows>
            ) : (
              <PanelEmpty>{t("reportBuilder.noneSaved")}</PanelEmpty>
            )}
          </RuledPanel>
        }
      />
      {run.data ? (
        <section aria-label={t("reportBuilder.results")} className="space-y-3">
          <ResultPanel
            result={run.data}
            title={title}
            aside={
              <span className="text-muted-foreground tabular-nums">
                {t("reportBuilder.generated", {
                  date: formatDateTime(run.data.generated_at, i18n.language),
                })}
              </span>
            }
            footer={
              <div className="flex w-full flex-wrap items-start justify-between gap-x-6 gap-y-3">
                <form
                  className="flex flex-wrap items-start gap-x-3 gap-y-2"
                  aria-label={t("reportBuilder.saveForm")}
                  onSubmit={(e) => {
                    e.preventDefault();
                    save.mutate();
                  }}
                >
                  <div className="w-full sm:w-56">
                    <TextField
                      size="sm"
                      hideLabel
                      label={t("reportBuilder.name")}
                      placeholder={t("reportBuilder.name")}
                      value={name}
                      required
                      onChange={(e) => setName(e.target.value)}
                    />
                  </div>
                  <label className="flex h-9 items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={shared}
                      onChange={(e) => setShared(e.target.checked)}
                    />
                    {t("reportBuilder.share")}
                  </label>
                  <Button
                    type="submit"
                    size="sm"
                    variant="secondary"
                    className="h-9"
                    loading={save.isPending}
                    disabled={!name.trim()}
                  >
                    {current?.is_mine ? t("reportBuilder.update") : t("reportBuilder.save")}
                  </Button>
                  {save.isSuccess ? (
                    <p role="status" className="flex h-9 items-center text-success">
                      {t("reportBuilder.savedOk")}
                    </p>
                  ) : null}
                </form>
                {canExport ? (
                  <div
                    role="group"
                    aria-label={t("reporting.export")}
                    className="flex flex-wrap items-center gap-2"
                  >
                    <span className="text-muted-foreground">{t("reporting.export")}</span>
                    {(["csv", "xlsx", "pdf"] as const).map((fmt) => (
                      <Button
                        key={fmt}
                        variant="secondary"
                        size="sm"
                        disabled={exportFile.isPending}
                        onClick={() => exportFile.mutate(fmt)}
                      >
                        {t(`reporting.formats.${fmt}`)}
                      </Button>
                    ))}
                  </div>
                ) : null}
              </div>
            }
          />
          {exportFile.error ? <Alert tone="danger">{exportFile.error.message}</Alert> : null}
        </section>
      ) : null}
    </ReportsPage>
  );
}
