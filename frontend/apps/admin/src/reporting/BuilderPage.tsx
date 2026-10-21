import { ApiError, unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { Chart } from "./Chart";
import { ReportsNav, ResultTable, ScheduleForm } from "./ReportingPages";

type Dataset = components["schemas"]["BuilderDataset"];
type Dimension = components["schemas"]["BuilderDimension"];
type Saved = components["schemas"]["CustomReport"];
type Output = components["schemas"]["CustomResult"];
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
    <fieldset className="space-y-2">
      <legend className="font-medium">{t("reportBuilder.columns")}</legend>
      <ul className="flex flex-wrap gap-2">
        {value.map((key) => {
          const [base, g] = key.split(":");
          const d = dataset.dimensions.find((x) => x.key === base);
          const label = `${d?.label ?? base}${g ? ` (${t(`reportBuilder.grains.${g}`)})` : ""}`;
          return (
            <li
              key={key}
              className="flex items-center gap-1 rounded-md border border-border px-2 text-sm"
            >
              {label}
              <Button
                size="sm"
                variant="ghost"
                aria-label={t("reportBuilder.removeColumn", { name: label })}
                onClick={() => onChange(value.filter((v) => v !== key))}
              >
                ×
              </Button>
            </li>
          );
        })}
      </ul>
      {value.length < 3 ? (
        <div className="flex flex-wrap items-end gap-2">
          <SelectField
            label={t("reportBuilder.addColumn")}
            value={dim}
            onChange={(e) => setDim(e.target.value)}
            options={[
              { value: "", label: t("reportBuilder.choose") },
              ...dataset.dimensions.map((d) => ({ value: d.key, label: d.label })),
            ]}
          />
          {selected?.type === "date" ? (
            <SelectField
              label={t("reportBuilder.grain")}
              value={grain}
              onChange={(e) => setGrain(e.target.value)}
              options={selected.grains.map((g) => ({
                value: g,
                label: t(`reportBuilder.grains.${g}`),
              }))}
            />
          ) : null}
          <Button
            variant="secondary"
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
        <p className="text-sm text-muted-foreground">{t("reportBuilder.maxColumns")}</p>
      )}
    </fieldset>
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
    <fieldset className="space-y-2">
      <legend className="font-medium">{t("reportBuilder.filters")}</legend>
      {filters.map((f, i) => {
        const dim = dataset.dimensions.find((d) => d.key === f.field);
        const ops = (dim?.operators ?? ["eq"]) as Op[];
        return (
          <div
            key={i}
            role="group"
            aria-label={t("reportBuilder.filterN", { n: i + 1 })}
            className="flex flex-wrap items-end gap-2"
          >
            <SelectField
              label={t("reportBuilder.field")}
              value={f.field}
              onChange={(e) => set(i, { field: e.target.value, op: "eq", value: "" })}
              options={[
                { value: "", label: t("reportBuilder.choose") },
                ...dataset.dimensions.map((d) => ({ value: d.key, label: d.label })),
              ]}
            />
            <SelectField
              label={t("reportBuilder.operator")}
              value={f.op}
              onChange={(e) => set(i, { op: e.target.value as Op })}
              options={ops.map((op) => ({ value: op, label: t(`reportBuilder.ops.${op}`) }))}
            />
            {f.op === "empty" || f.op === "not_empty" ? null : dim?.choices.length &&
              f.op !== "in" ? (
              <SelectField
                label={t("reportBuilder.value")}
                value={f.value}
                onChange={(e) => set(i, { value: e.target.value })}
                options={[
                  { value: "", label: t("reportBuilder.choose") },
                  ...dim.choices.map((c) => ({ value: c.value, label: c.label })),
                ]}
              />
            ) : dim?.type === "bool" ? (
              <SelectField
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
                label={t("reportBuilder.value")}
                hint={f.op === "in" ? t("reportBuilder.commaHint") : undefined}
                type={dim?.type === "date" && f.op !== "in" ? "date" : "text"}
                value={f.value}
                onChange={(e) => set(i, { value: e.target.value })}
              />
            )}
            <Button
              variant="ghost"
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
          variant="secondary"
          onClick={() => onChange([...filters, { field: "", op: "eq", value: "" }])}
        >
          {t("reportBuilder.addFilter")}
        </Button>
      ) : null}
    </fieldset>
  );
}

function Results({ output, title }: { output: Output; title: string }) {
  const { t } = useTranslation();
  const chart = output.chart;
  const labels = Object.fromEntries(output.columns.map((c) => [c.key, c.label]));
  const data = chart
    ? output.rows.map((row) => ({
        x: [row[chart.x], typeof row.currency === "string" ? row.currency : ""]
          .filter(Boolean)
          .join(" "),
        ...Object.fromEntries(chart.y.map((k) => [k, Number(row[k] ?? 0)])),
      }))
    : [];
  return (
    <section aria-label={t("reportBuilder.results")} className="space-y-3">
      {output.period ? (
        <p className="text-sm text-muted-foreground">
          {t("reporting.showing", {
            from: formatDate(String(output.period.from)),
            to: formatDate(String(output.period.to)),
          })}
        </p>
      ) : null}
      {chart && data.length ? (
        <Chart
          kind={chart.kind}
          data={data as Array<Record<string, string | number>>}
          series={chart.y.map((k) => ({ key: k, label: labels[k] ?? k }))}
          label={t("reporting.chartOf", { name: title })}
          xLabel={labels[chart.x] ?? chart.x}
          srTable={false}
        />
      ) : null}
      <ResultTable result={output} caption={title} />
      {output.notes.map((n) => (
        <p key={n} className="text-sm text-muted-foreground">
          {n}
        </p>
      ))}
      <p className="text-xs text-muted-foreground">
        {t("reportBuilder.generated", { date: formatDateTime(output.generated_at) })}
      </p>
    </section>
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
  const { t } = useTranslation();
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
  return (
    <section className="space-y-6">
      <ReportsNav />
      <h1 className="text-2xl font-semibold">{t("reportBuilder.title")}</h1>
      <p className="text-muted-foreground">{t("reportBuilder.intro")}</p>
      {datasets.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {datasets.data?.length === 0 ? <p>{t("reportBuilder.noDatasets")}</p> : null}
      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        {dataset ? (
          <form
            className="space-y-4 rounded-lg border border-border p-4"
            aria-label={t("reportBuilder.form")}
            onSubmit={(e) => {
              e.preventDefault();
              run.mutate();
            }}
          >
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
            <GroupByPicker
              dataset={dataset}
              value={def.group_by}
              onChange={(group_by) => setDef({ ...def, group_by })}
            />
            <fieldset>
              <legend className="font-medium">{t("reportBuilder.measures")}</legend>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
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
            </fieldset>
            <FilterRows
              dataset={dataset}
              filters={def.filters}
              onChange={(filters) => setDef({ ...def, filters })}
            />
            <div className="flex flex-wrap items-end gap-3">
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
                onChange={(e) => setDef({ ...def, chart: e.target.value as Definition["chart"] })}
                options={CHARTS.map((c) => ({ value: c, label: t(`reportBuilder.charts.${c}`) }))}
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
                      { value: `-${key}`, label: t("reportBuilder.descending", { name: label }) },
                    ];
                  }),
                ]}
              />
              <TextField
                label={t("reportBuilder.limit")}
                type="number"
                min={1}
                max={1000}
                value={String(def.limit)}
                onChange={(e) => setDef({ ...def, limit: Number(e.target.value) || 200 })}
              />
              <TextField
                label={t("reporting.currency")}
                hint={t("reporting.currencyHint")}
                maxLength={3}
                value={def.currency}
                onChange={(e) => setDef({ ...def, currency: e.target.value.toUpperCase() })}
              />
            </div>
            {Object.keys(errors).length ? (
              <Alert tone="danger" title={t("reportBuilder.invalid")}>
                {Object.values(errors).join(" ")}
              </Alert>
            ) : runError ? (
              <Alert tone="danger">{runError}</Alert>
            ) : null}
            <Button type="submit" disabled={run.isPending}>
              {t("reportBuilder.run")}
            </Button>
          </form>
        ) : null}
        <aside className="space-y-3" aria-labelledby="custom-saved">
          <h2 id="custom-saved" className="text-lg font-semibold">
            {t("reportBuilder.saved")}
          </h2>
          {scheduledName ? (
            <p role="status" className="text-sm">
              {t("reportingG5.scheduled", { name: scheduledName })}
            </p>
          ) : null}
          {saved.data?.results.length ? (
            <ul className="space-y-2 text-sm">
              {saved.data.results.map((r) => (
                <li key={r.id} className="rounded-md border border-border p-2">
                  <Button variant="ghost" size="sm" onClick={() => open(r)}>
                    {r.name}
                  </Button>
                  <p className="text-muted-foreground">
                    {r.is_mine
                      ? r.shared
                        ? t("reportBuilder.sharedByYou")
                        : t("reportBuilder.private")
                      : t("reportBuilder.sharedBy", { name: r.owner_name })}
                  </p>
                  {r.is_mine ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t("reportBuilder.deleteNamed", { name: r.name })}
                      onClick={() => remove.mutate(r.id)}
                    >
                      {t("reportBuilder.delete")}
                    </Button>
                  ) : null}
                  {r.is_mine && canSchedule && canExport ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-expanded={scheduling === r.id}
                      aria-label={t("reportingG5.scheduleNamed", { name: r.name })}
                      onClick={() => setScheduling(scheduling === r.id ? null : r.id)}
                    >
                      {t("reporting.scheduleEmail")}
                    </Button>
                  ) : null}
                  {scheduling === r.id ? (
                    <ScheduleForm
                      saved={{ id: r.id, name: r.name, kind: "custom" }}
                      onDone={() => {
                        setScheduling(null);
                        setScheduled(r.name);
                        void queryClient.invalidateQueries({ queryKey: ["scheduled-reports"] });
                      }}
                    />
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm">{t("reportBuilder.noneSaved")}</p>
          )}
        </aside>
      </div>
      {run.data ? (
        <>
          <Results output={run.data} title={name || dataset?.label || ""} />
          <form
            className="flex flex-wrap items-end gap-3"
            aria-label={t("reportBuilder.saveForm")}
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <TextField
              label={t("reportBuilder.name")}
              value={name}
              required
              onChange={(e) => setName(e.target.value)}
            />
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={shared}
                onChange={(e) => setShared(e.target.checked)}
              />
              {t("reportBuilder.share")}
            </label>
            <Button type="submit" variant="secondary" disabled={save.isPending || !name.trim()}>
              {current?.is_mine ? t("reportBuilder.update") : t("reportBuilder.save")}
            </Button>
            {save.isSuccess ? <p role="status">{t("reportBuilder.savedOk")}</p> : null}
          </form>
          {canExport ? (
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span>{t("reporting.export")}:</span>
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
              {exportFile.error ? <Alert tone="danger">{exportFile.error.message}</Alert> : null}
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
