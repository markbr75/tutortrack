import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useMemo, useState, type FormEvent, type ReactNode } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { Chart } from "./Chart";

type ReportDef = components["schemas"]["ReportDefinition"];
type Result = components["schemas"]["ReportResult"];
type Column = components["schemas"]["ReportColumn"];
type WidgetData = components["schemas"]["WidgetData"];
type WidgetInfo = components["schemas"]["WidgetInfo"];
type LayoutItem = components["schemas"]["LayoutItem"];
type Saved = components["schemas"]["SavedReport"];
type Scheduled = components["schemas"]["ScheduledReport"];
type Run = components["schemas"]["ReportRun"];
type Cell = Record<string, unknown>;

const PRESETS = [
  "today",
  "this_week",
  "last_week",
  "this_month",
  "last_month",
  "this_quarter",
  "last_quarter",
  "this_year",
  "last_year",
  "last_30_days",
  "last_90_days",
  "last_12_months",
  "custom",
] as const;
const COMPARISONS = ["previous_period", "previous_year", "none"] as const;
const SIZES = { s: "md:col-span-1", m: "md:col-span-2", l: "md:col-span-3" } as const;
const linkClass = "underline underline-offset-2";

function useLocale(): string {
  const { i18n } = useTranslation();
  return i18n.language || "en-GB";
}

/** Displays a report or widget value: money with its currency, otherwise as given. */
function useFormat() {
  const locale = useLocale();
  return (value: unknown, type: string, currency?: string): string => {
    if (value === null || value === undefined || value === "") return "";
    const text = String(value);
    if (type === "money" && currency && /^-?\d+(\.\d+)?$/.test(text)) {
      return formatMoney({ amount: text, currency }, locale);
    }
    if (type === "percent") return `${text}%`;
    if (type === "date" && /^\d{4}-\d{2}-\d{2}$/.test(text)) return formatDate(text, locale);
    if (
      /^-?\d+(\.\d+)?$/.test(text) &&
      (type === "count" || type === "number" || type === "hours")
    ) {
      return new Intl.NumberFormat(locale).format(Number(text));
    }
    return text;
  };
}

function PeriodFields({
  period,
  from,
  to,
  onChange,
}: {
  period: string;
  from: string;
  to: string;
  onChange: (next: { period: string; from: string; to: string }) => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      <SelectField
        label={t("reporting.period")}
        value={period}
        onChange={(e) => onChange({ period: e.target.value, from, to })}
        options={PRESETS.map((p) => ({ value: p, label: t(`reporting.periods.${p}`) }))}
      />
      {period === "custom" ? (
        <>
          <TextField
            type="date"
            label={t("reporting.from")}
            value={from}
            onChange={(e) => onChange({ period, from: e.target.value, to })}
          />
          <TextField
            type="date"
            label={t("reporting.to")}
            value={to}
            onChange={(e) => onChange({ period, from, to: e.target.value })}
          />
        </>
      ) : null}
    </>
  );
}

function periodQuery(p: { period: string; from: string; to: string }): Record<string, string> {
  return p.period === "custom"
    ? { period: "custom", from: p.from, to: p.to }
    : { period: p.period };
}

// --- dashboard ------------------------------------------------------------------------------

function Change({ value, previous }: { value: string; previous: string | null }) {
  const { t } = useTranslation();
  if (previous === null) return null;
  const now = Number(value);
  const before = Number(previous);
  if (Number.isNaN(now) || Number.isNaN(before)) return null;
  if (before === 0) {
    return <span className="text-xs text-muted-foreground">{t("reporting.noComparison")}</span>;
  }
  const change = ((now - before) / Math.abs(before)) * 100;
  const rounded = Math.round(change * 10) / 10;
  const key = rounded > 0 ? "reporting.up" : rounded < 0 ? "reporting.down" : "reporting.same";
  return (
    <span className="text-xs text-muted-foreground">{t(key, { percent: Math.abs(rounded) })}</span>
  );
}

function reportLink(data: WidgetData): string | null {
  if (!data.widget.report) return null;
  const search = new URLSearchParams(data.report_params as Record<string, string>);
  return `/analytics/${data.widget.report}?${search.toString()}`;
}

function WidgetTile({
  item,
  query,
  editing,
  controls,
}: {
  item: LayoutItem;
  query: Record<string, string>;
  editing: boolean;
  controls: ReactNode;
}) {
  const { t } = useTranslation();
  const format = useFormat();
  const widget = useQuery({
    queryKey: ["widget", item.widget, query],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/reporting/widgets/{key}", {
          params: { path: { key: item.widget }, query },
        }),
      ),
  });
  const data = widget.data;
  const title = data?.widget.title ?? item.widget;
  const href = data ? reportLink(data) : null;
  const series = data?.series ?? [];
  const seriesKeys = series.length ? Object.keys(series[0]?.y ?? {}) : [];
  return (
    <section
      aria-label={title}
      className={`space-y-2 rounded-lg border border-border p-4 ${SIZES[item.size ?? "s"]}`}
    >
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-medium text-muted-foreground">{title}</h2>
        {href && !editing ? (
          <a
            href={href}
            className={`${linkClass} text-xs`}
            aria-label={t("reporting.openReportFor", { name: title })}
          >
            {t("reporting.openReport")}
          </a>
        ) : null}
      </div>
      {widget.isPending ? <Spinner className="size-4" label={t("grid.loading")} /> : null}
      {widget.isError ? <p className="text-sm">{t("reporting.widgetError")}</p> : null}
      {data ? (
        <>
          {data.values.length === 0 && data.rows.length === 0 && series.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("reporting.nothing")}</p>
          ) : null}
          {data.values.length ? (
            <dl className="space-y-1">
              {data.values.map((v, i) => (
                <div key={i}>
                  {v.label ? <dt className="text-xs text-muted-foreground">{v.label}</dt> : null}
                  <dd className="flex flex-wrap items-baseline gap-2">
                    <span className="text-2xl font-semibold">
                      {format(v.value, data.unit, v.currency)}
                    </span>
                    <Change value={v.value} previous={v.previous} />
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
          {data.rows.length ? (
            <ul className="divide-y divide-border text-sm">
              {data.rows.map((r, i) => (
                <li key={i} className="flex justify-between gap-2 py-1">
                  <span>{r.label}</span>
                  <span className="text-right">
                    {data.unit === "money" && r.detail
                      ? format(r.value, "money", r.detail)
                      : r.value}
                    {data.unit !== "money" && r.detail ? (
                      <span className="block text-xs text-muted-foreground">{r.detail}</span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {series.length ? (
            <Chart
              kind="line"
              label={title}
              xLabel={t("reporting.date")}
              data={series.map((p) => ({
                x: p.currency ? `${p.x} ${p.currency}` : p.x,
                ...Object.fromEntries(Object.entries(p.y).map(([k, v]) => [k, Number(v)])),
              }))}
              series={seriesKeys.map((k) => ({ key: k, label: t(`reporting.series.${k}`) }))}
              height={180}
            />
          ) : null}
        </>
      ) : null}
      {editing ? controls : null}
    </section>
  );
}

/** The configurable dashboard (FR-26-1): KPI tiles, lists and charts for a period. */
export function Dashboard() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [period, setPeriod] = useState({ period: "this_month", from: "", to: "" });
  const [compare, setCompare] = useState("previous_period");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<LayoutItem[]>([]);
  const [adding, setAdding] = useState("");
  const layout = useQuery({
    queryKey: ["dashboard"],
    queryFn: async () => unwrap(await api.GET("/api/v1/reporting/dashboard")),
  });
  const library = useQuery({
    queryKey: ["widgets"],
    queryFn: async () => unwrap(await api.GET("/api/v1/reporting/widgets")),
    enabled: editing,
  });
  const save = useMutation({
    mutationFn: async (widgets: LayoutItem[]) =>
      unwrap(await api.PUT("/api/v1/reporting/dashboard", { body: { widgets } })),
    onSuccess: (data) => {
      queryClient.setQueryData(["dashboard"], data);
      setEditing(false);
    },
  });
  const reset = useMutation({
    mutationFn: async () => unwrap(await api.DELETE("/api/v1/reporting/dashboard")),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setEditing(false);
    },
  });
  if (!layout.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const query = { ...periodQuery(period), compare };
  const items = editing ? draft : layout.data.widgets;
  const titles = Object.fromEntries((library.data ?? []).map((w: WidgetInfo) => [w.key, w.title]));
  const move = (index: number, by: number) => {
    const next = [...draft];
    const [item] = next.splice(index, 1);
    if (item) next.splice(index + by, 0, item);
    setDraft(next);
  };
  return (
    <section aria-labelledby="dashboard-title" className="mt-6 space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <h2 id="dashboard-title" className="mr-auto text-lg font-medium">
          {t("reporting.dashboard")}
        </h2>
        <PeriodFields {...period} onChange={setPeriod} />
        <SelectField
          label={t("reporting.compare")}
          value={compare}
          onChange={(e) => setCompare(e.target.value)}
          options={COMPARISONS.map((c) => ({ value: c, label: t(`reporting.comparisons.${c}`) }))}
        />
        {editing ? (
          <>
            <Button onClick={() => save.mutate(draft)} disabled={save.isPending}>
              {t("reporting.saveLayout")}
            </Button>
            <Button variant="secondary" onClick={() => setEditing(false)}>
              {t("common.cancel")}
            </Button>
            {layout.data.customised ? (
              <Button variant="secondary" onClick={() => reset.mutate()}>
                {t("reporting.resetLayout")}
              </Button>
            ) : null}
          </>
        ) : (
          <Button
            variant="secondary"
            onClick={() => {
              setDraft(layout.data.widgets);
              setEditing(true);
            }}
          >
            {t("reporting.customise")}
          </Button>
        )}
      </div>
      {save.isError ? <Alert tone="danger">{fieldErrors(save.error).widgets}</Alert> : null}
      {editing ? (
        <div className="flex flex-wrap items-end gap-2">
          <SelectField
            label={t("reporting.addWidget")}
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            options={[
              { value: "", label: t("reporting.chooseWidget") },
              ...(library.data ?? [])
                .filter((w) => !draft.some((d) => d.widget === w.key))
                .map((w) => ({ value: w.key, label: w.title })),
            ]}
          />
          <Button
            variant="secondary"
            disabled={!adding}
            onClick={() => {
              const info = library.data?.find((w) => w.key === adding);
              setDraft([...draft, { widget: adding, size: (info?.default_size ?? "s") as "s" }]);
              setAdding("");
            }}
          >
            {t("reporting.add")}
          </Button>
        </div>
      ) : null}
      {items.length === 0 ? <p>{t("reporting.emptyDashboard")}</p> : null}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {items.map((item, index) => {
          const name = titles[item.widget] ?? item.widget;
          return (
            <WidgetTile
              key={item.widget}
              item={item}
              query={query}
              editing={editing}
              controls={
                <div className="flex flex-wrap items-end gap-2 border-t border-border pt-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                    aria-label={t("reporting.moveEarlier", { name })}
                  >
                    {t("reporting.earlier")}
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={index === items.length - 1}
                    onClick={() => move(index, 1)}
                    aria-label={t("reporting.moveLater", { name })}
                  >
                    {t("reporting.later")}
                  </Button>
                  <SelectField
                    label={t("reporting.size", { name })}
                    value={item.size ?? "s"}
                    onChange={(e) =>
                      setDraft(
                        draft.map((d, i) =>
                          i === index ? { ...d, size: e.target.value as "s" | "m" | "l" } : d,
                        ),
                      )
                    }
                    options={(["s", "m", "l"] as const).map((s) => ({
                      value: s,
                      label: t(`reporting.sizes.${s}`),
                    }))}
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setDraft(draft.filter((_, i) => i !== index))}
                    aria-label={t("reporting.remove", { name })}
                  >
                    {t("reporting.removeShort")}
                  </Button>
                </div>
              }
            />
          );
        })}
      </div>
    </section>
  );
}

// --- report library -------------------------------------------------------------------------

function ReportsNav() {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("reporting.sections")} className="flex gap-4 text-sm">
      <Link to="/analytics" className={linkClass} activeOptions={{ exact: true }}>
        {t("reporting.library")}
      </Link>
      <Link to="/analytics/saved" className={linkClass}>
        {t("reporting.savedTitle")}
      </Link>
    </nav>
  );
}

export function ReportsLibraryPage() {
  const { t } = useTranslation();
  const reports = useQuery({
    queryKey: ["reports"],
    queryFn: async () => unwrap(await api.GET("/api/v1/reporting/reports")),
  });
  const groups = useMemo(() => {
    const out = new Map<string, { label: string; items: ReportDef[] }>();
    for (const r of reports.data ?? []) {
      const group = out.get(r.category) ?? { label: r.category_label, items: [] };
      group.items.push(r);
      out.set(r.category, group);
    }
    return [...out.entries()];
  }, [reports.data]);
  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("reporting.title")}</h1>
      <ReportsNav />
      {reports.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      {reports.data?.length === 0 ? <p>{t("reporting.noReports")}</p> : null}
      {groups.map(([key, group]) => (
        <section key={key} aria-labelledby={`cat-${key}`} className="space-y-2">
          <h2 id={`cat-${key}`} className="text-lg font-medium">
            {group.label}
          </h2>
          <ul className="grid gap-3 md:grid-cols-2">
            {group.items.map((r) => (
              <li key={r.key} className="rounded-lg border border-border p-3">
                <a
                  href={`/analytics/${r.key}`}
                  className="font-medium underline-offset-2 hover:underline"
                >
                  {r.title}
                </a>
                <p className="text-sm text-muted-foreground">{r.description}</p>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </section>
  );
}

// --- one report -----------------------------------------------------------------------------

const FILTER_KEYS = ["tutor", "service", "client"] as const;

function initialParams(): Record<string, string> {
  if (typeof window === "undefined") return {};
  return Object.fromEntries(new URLSearchParams(window.location.search).entries());
}

function useFilterOptions(filter: string, enabled: boolean) {
  return useQuery({
    queryKey: ["report-filter", filter],
    enabled,
    queryFn: async (): Promise<Array<{ value: string; label: string }>> => {
      if (filter === "tutor") {
        const page = unwrap(
          await api.GET("/api/v1/tutors", { params: { query: { page_size: 200 } } }),
        );
        return page.results.map((r) => ({
          value: r.id,
          label: [r.first_name, r.last_name].filter(Boolean).join(" "),
        }));
      }
      if (filter === "service") {
        const rows = unwrap(await api.GET("/api/v1/catalogue/services"));
        const list = Array.isArray(rows) ? rows : rows.results;
        return list.map((r) => ({ value: r.id, label: r.name }));
      }
      const page = unwrap(
        await api.GET("/api/v1/clients", { params: { query: { page_size: 200 } } }),
      );
      return page.results.map((r) => ({ value: r.id, label: r.display_name }));
    },
  });
}

function FilterSelect({
  filter,
  value,
  onChange,
}: {
  filter: (typeof FILTER_KEYS)[number];
  value: string;
  onChange: (v: string) => void;
}) {
  const { t } = useTranslation();
  const options = useFilterOptions(filter, true);
  return (
    <SelectField
      label={t(`reporting.filters.${filter}`)}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      options={[{ value: "", label: t("reporting.all") }, ...(options.data ?? [])]}
    />
  );
}

function ResultTable({ result, caption }: { result: Result; caption: string }) {
  const format = useFormat();
  const rows = result.rows as Cell[];
  const totals = result.totals as Cell[];
  const cols = result.columns;
  const { t } = useTranslation();
  const show = (col: Column, row: Cell) =>
    format(row[col.key], col.type, typeof row.currency === "string" ? row.currency : undefined);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="text-left font-semibold">{caption}</caption>
        <thead>
          <tr className="text-left">
            {cols.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`px-2 py-1 ${c.type === "text" || c.type === "date" ? "" : "text-right"}`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={cols.length} className="px-2 py-3 text-muted-foreground">
                {t("reporting.nothing")}
              </td>
            </tr>
          ) : null}
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-border">
              {cols.map((c) => (
                <td
                  key={c.key}
                  className={`px-2 py-1 ${c.type === "text" || c.type === "date" ? "" : "text-right"}`}
                >
                  {show(c, row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {totals.length ? (
          <tfoot>
            {totals.map((row, i) => (
              <tr key={i} className="border-t-2 border-border font-semibold">
                {cols.map((c, j) => (
                  <td
                    key={c.key}
                    className={`px-2 py-1 ${c.type === "text" || c.type === "date" ? "" : "text-right"}`}
                  >
                    {j === 0 ? t("reporting.total") : c.key in row ? show(c, row) : ""}
                  </td>
                ))}
              </tr>
            ))}
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}

function SaveView({ reportKey, params }: { reportKey: string; params: Record<string, string> }) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/saved-reports", {
          body: { name, report_key: reportKey, params, shared },
        }),
      ),
    onSuccess: () => setName(""),
  });
  const errors = fieldErrors(save.error);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form
      onSubmit={submit}
      className="flex flex-wrap items-end gap-3"
      aria-label={t("reporting.saveView")}
    >
      <TextField
        label={t("reporting.viewName")}
        value={name}
        onChange={(e) => setName(e.target.value)}
        error={errors.name}
        required
      />
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
        {t("reporting.shareView")}
      </label>
      <Button type="submit" variant="secondary" disabled={save.isPending}>
        {t("reporting.saveView")}
      </Button>
      {save.isSuccess ? <p role="status">{t("reporting.viewSaved")}</p> : null}
    </form>
  );
}

export function ReportViewPage({ reportKey }: { reportKey: string }) {
  const { t } = useTranslation();
  const canExport = usePermission("reporting.export");
  const initial = useMemo(initialParams, []);
  const [params, setParams] = useState<Record<string, string>>(initial);
  const defs = useQuery({
    queryKey: ["reports"],
    queryFn: async () => unwrap(await api.GET("/api/v1/reporting/reports")),
  });
  const report = useQuery({
    queryKey: ["report", reportKey, params],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/reporting/reports/{key}", {
          params: { path: { key: reportKey }, query: params },
        }),
      ),
  });
  const def = defs.data?.find((r) => r.key === reportKey) ?? report.data?.report;
  const result = report.data;
  const set = (changes: Record<string, string>) => {
    const next = Object.fromEntries(
      Object.entries({ ...params, ...changes }).filter(([, v]) => v !== ""),
    );
    setParams(next);
    window.history.replaceState(null, "", `?${new URLSearchParams(next).toString()}`);
  };
  const exportHref = (fmt: string) =>
    `/api/v1/reporting/reports/${reportKey}/export?${new URLSearchParams({
      ...(result?.params as Record<string, string> | undefined),
      file_format: fmt,
    }).toString()}`;
  const errors = fieldErrors(report.error);
  const title = def?.title ?? reportKey;
  const chart = result?.chart;
  const chartData =
    chart && result
      ? (result.rows as Cell[]).map((row) => ({
          x: [row[chart.x], typeof row.currency === "string" ? row.currency : ""]
            .filter(Boolean)
            .join(" "),
          ...Object.fromEntries(chart.y.map((k) => [k, Number(row[k] ?? 0)])),
        }))
      : [];
  const labels = Object.fromEntries((result?.columns ?? []).map((c) => [c.key, c.label]));
  return (
    <section className="space-y-4">
      <ReportsNav />
      <h1 className="text-2xl font-semibold">{title}</h1>
      {def ? <p className="text-muted-foreground">{def.description}</p> : null}
      {def ? (
        <form
          aria-label={t("reporting.filtersLabel")}
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => e.preventDefault()}
        >
          {def.period ? (
            <PeriodFields
              period={params.period ?? def.default_period}
              from={params.from ?? ""}
              to={params.to ?? ""}
              onChange={(p) => set({ period: p.period, from: p.from, to: p.to })}
            />
          ) : null}
          {def.group_by.length ? (
            <SelectField
              label={t("reporting.groupBy")}
              value={params.group_by ?? def.group_by[0]?.value ?? ""}
              onChange={(e) => set({ group_by: e.target.value })}
              options={def.group_by}
            />
          ) : null}
          {FILTER_KEYS.filter((f) => def.filters.includes(f)).map((f) => (
            <FilterSelect
              key={f}
              filter={f}
              value={params[f] ?? ""}
              onChange={(v) => set({ [f]: v })}
            />
          ))}
          <TextField
            label={t("reporting.currency")}
            hint={t("reporting.currencyHint")}
            value={params.currency ?? ""}
            maxLength={3}
            onChange={(e) => {
              const v = e.target.value.toUpperCase();
              if (v.length === 0 || v.length === 3) set({ currency: v });
            }}
          />
        </form>
      ) : null}
      {report.isError ? (
        <Alert tone="danger" title={t("reporting.runError")}>
          {Object.values(errors).join(" ")}
        </Alert>
      ) : null}
      {report.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      {result ? (
        <>
          {result.period ? (
            <p className="text-sm text-muted-foreground">
              {t("reporting.showing", {
                from: formatDate(String(result.period.from)),
                to: formatDate(String(result.period.to)),
              })}
            </p>
          ) : null}
          {chart && chartData.length ? (
            <Chart
              kind={chart.kind}
              data={chartData}
              series={chart.y.map((k) => ({ key: k, label: labels[k] ?? k }))}
              label={t("reporting.chartOf", { name: title })}
              xLabel={labels[chart.x] ?? chart.x}
              stacked={chart.stacked}
              srTable={false}
            />
          ) : null}
          <ResultTable result={result} caption={title} />
          {result.notes.map((n) => (
            <p key={n} className="text-sm text-muted-foreground">
              {n}
            </p>
          ))}
          {canExport ? (
            <div className="flex flex-wrap gap-3 text-sm">
              <span>{t("reporting.export")}:</span>
              {(["csv", "xlsx", "pdf"] as const).map((fmt) => (
                <a key={fmt} href={exportHref(fmt)} className={linkClass} download>
                  {t(`reporting.formats.${fmt}`)}
                </a>
              ))}
            </div>
          ) : null}
          <SaveView reportKey={reportKey} params={result.params as Record<string, string>} />
        </>
      ) : null}
    </section>
  );
}

// --- saved and scheduled reports ------------------------------------------------------------

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

function ScheduleForm({ saved, onDone }: { saved: Saved; onDone: () => void }) {
  const { t } = useTranslation();
  const [frequency, setFrequency] = useState("weekly");
  const [weekday, setWeekday] = useState("0");
  const [day, setDay] = useState("1");
  const [time, setTime] = useState("07:00");
  const [format, setFormat] = useState("csv");
  const [recipients, setRecipients] = useState<string[]>([]);
  const staff = useQuery({
    queryKey: ["report-recipients"],
    queryFn: async () => unwrap(await api.GET("/api/v1/scheduled-reports/recipients")),
  });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/scheduled-reports", {
          body: {
            saved_report: saved.id,
            frequency: frequency as "weekly",
            weekday: Number(weekday),
            day_of_month: Number(day),
            time,
            format: format as "csv",
            recipients,
          },
        }),
      ),
    onSuccess: onDone,
  });
  const errors = fieldErrors(create.error);
  return (
    <form
      aria-label={t("reporting.scheduleFor", { name: saved.name })}
      className="space-y-3 rounded-md border border-border p-3"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <div className="flex flex-wrap items-end gap-3">
        <SelectField
          label={t("reporting.frequency")}
          value={frequency}
          onChange={(e) => setFrequency(e.target.value)}
          options={(["daily", "weekly", "monthly"] as const).map((f) => ({
            value: f,
            label: t(`reporting.frequencies.${f}`),
          }))}
        />
        {frequency === "weekly" ? (
          <SelectField
            label={t("reporting.weekday")}
            value={weekday}
            onChange={(e) => setWeekday(e.target.value)}
            options={WEEKDAYS.map((d, i) => ({
              value: String(i),
              label: t(`reporting.weekdays.${d}`),
            }))}
          />
        ) : null}
        {frequency === "monthly" ? (
          <TextField
            type="number"
            min={1}
            max={28}
            label={t("reporting.dayOfMonth")}
            value={day}
            onChange={(e) => setDay(e.target.value)}
            error={errors.day_of_month}
          />
        ) : null}
        <TextField
          type="time"
          label={t("reporting.time")}
          value={time}
          onChange={(e) => setTime(e.target.value)}
          error={errors.time}
        />
        <SelectField
          label={t("reporting.format")}
          value={format}
          onChange={(e) => setFormat(e.target.value)}
          options={(["csv", "xlsx", "pdf"] as const).map((f) => ({
            value: f,
            label: t(`reporting.formats.${f}`),
          }))}
        />
      </div>
      <fieldset>
        <legend className="text-sm font-medium">{t("reporting.recipients")}</legend>
        {(staff.data ?? []).map((s) => (
          <label key={s.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={recipients.includes(s.id)}
              onChange={(e) =>
                setRecipients(
                  e.target.checked ? [...recipients, s.id] : recipients.filter((r) => r !== s.id),
                )
              }
            />
            {s.name} ({s.email})
          </label>
        ))}
        {errors.recipients ? (
          <p className="text-sm text-destructive" role="alert">
            {errors.recipients}
          </p>
        ) : null}
      </fieldset>
      <Button type="submit" disabled={create.isPending}>
        {t("reporting.schedule")}
      </Button>
    </form>
  );
}

export function SavedReportsPage() {
  const { t } = useTranslation();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const canSchedule = usePermission("reporting.schedule.manage");
  const canExport = usePermission("reporting.export");
  const [scheduling, setScheduling] = useState<string | null>(null);
  const saved = useQuery({
    queryKey: ["saved-reports"],
    queryFn: async () => unwrap(await api.GET("/api/v1/saved-reports")),
  });
  const scheduled = useQuery({
    queryKey: ["scheduled-reports"],
    enabled: canSchedule,
    queryFn: async () => unwrap(await api.GET("/api/v1/scheduled-reports")),
  });
  const runs = useQuery({
    queryKey: ["report-runs"],
    enabled: canExport,
    queryFn: async () => unwrap(await api.GET("/api/v1/report-runs")),
  });
  const removeSaved = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/saved-reports/{id}", { params: { path: { id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["saved-reports"] }),
  });
  const toggle = useMutation({
    mutationFn: async (s: Scheduled) =>
      unwrap(
        await api.PATCH("/api/v1/scheduled-reports/{id}", {
          params: { path: { id: s.id } },
          body: { enabled: !s.enabled },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["scheduled-reports"] }),
  });
  const removeScheduled = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/scheduled-reports/{id}", { params: { path: { id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["scheduled-reports"] }),
  });
  const download = useMutation({
    mutationFn: async (run: Run) =>
      unwrap(
        await api.GET("/api/v1/report-runs/{id}/download", { params: { path: { id: run.id } } }),
      ),
    onSuccess: (data) => window.location.assign(data.url),
  });
  const viewHref = (s: Saved) =>
    `/analytics/${s.report_key}?${new URLSearchParams((s.params ?? {}) as Record<string, string>).toString()}`;
  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("reporting.savedTitle")}</h1>
      <ReportsNav />
      <section aria-labelledby="saved-views" className="space-y-2">
        <h2 id="saved-views" className="text-lg font-medium">
          {t("reporting.savedViews")}
        </h2>
        {saved.data?.results.length === 0 ? <p>{t("reporting.noSaved")}</p> : null}
        <ul className="space-y-3">
          {(saved.data?.results ?? []).map((s) => (
            <li key={s.id} className="space-y-2 rounded-lg border border-border p-3">
              <div className="flex flex-wrap items-center gap-3">
                <a href={viewHref(s)} className={`${linkClass} font-medium`}>
                  {s.name}
                </a>
                <span className="text-sm text-muted-foreground">
                  {s.shared
                    ? t("reporting.sharedBy", { name: s.owner_name })
                    : t("reporting.private")}
                </span>
                {canSchedule && s.is_mine ? (
                  <Button size="sm" variant="secondary" onClick={() => setScheduling(s.id)}>
                    {t("reporting.scheduleEmail")}
                  </Button>
                ) : null}
                {s.is_mine ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => removeSaved.mutate(s.id)}
                    aria-label={t("reporting.deleteView", { name: s.name })}
                  >
                    {t("reporting.delete")}
                  </Button>
                ) : null}
              </div>
              {scheduling === s.id ? (
                <ScheduleForm
                  saved={s}
                  onDone={() => {
                    setScheduling(null);
                    void queryClient.invalidateQueries({ queryKey: ["scheduled-reports"] });
                  }}
                />
              ) : null}
            </li>
          ))}
        </ul>
      </section>
      {canSchedule ? (
        <section aria-labelledby="scheduled" className="space-y-2">
          <h2 id="scheduled" className="text-lg font-medium">
            {t("reporting.scheduledTitle")}
          </h2>
          {scheduled.data?.results.length === 0 ? <p>{t("reporting.noScheduled")}</p> : null}
          <ul className="space-y-2">
            {(scheduled.data?.results ?? []).map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-3 text-sm">
                <span className="font-medium">{s.saved_report_name}</span>
                <span>
                  {t(`reporting.frequencies.${s.frequency}`)} · {s.time} ·{" "}
                  {t(`reporting.formats.${s.format ?? "csv"}`)}
                </span>
                <span className="text-muted-foreground">
                  {s.recipient_details.map((r) => r.name).join(", ")}
                </span>
                <Button size="sm" variant="secondary" onClick={() => toggle.mutate(s)}>
                  {s.enabled ? t("reporting.pause") : t("reporting.resume")}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => removeScheduled.mutate(s.id)}
                  aria-label={t("reporting.deleteSchedule", { name: s.saved_report_name })}
                >
                  {t("reporting.delete")}
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {canExport ? (
        <section aria-labelledby="runs" className="space-y-2">
          <h2 id="runs" className="text-lg font-medium">
            {t("reporting.runsTitle")}
          </h2>
          <ul className="space-y-1 text-sm">
            {(runs.data?.results ?? []).map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3">
                <span>{formatDateTime(r.created_at, locale)}</span>
                <span>{r.saved_report_name ?? r.report_key}</span>
                <span>{t(`reporting.runStatus.${r.status}`)}</span>
                <span>{t("reporting.rows", { count: r.row_count })}</span>
                {r.file_name ? (
                  <Button size="sm" variant="secondary" onClick={() => download.mutate(r)}>
                    {t("reporting.download")}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}
