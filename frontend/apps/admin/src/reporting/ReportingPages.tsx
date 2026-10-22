import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  cn,
  FigureStrip,
  figureCell,
  PageHeader,
  PanelRow,
  PanelRows,
  RuledPanel,
  RuledTable,
  SelectField,
  TextField,
  type RuledColumn,
  type StripFigure,
} from "@tutortrack/ui";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useMemo, useState, type FormEvent, type ReactNode } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { PanelEmpty, PanelLoading } from "../billing/moneyUi";
import { useIsPhone } from "../billing/useIsPhone";
import { RecordHeader } from "../components/RecordHeader";
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
/** Widths on the dashboard's six-column grid: a third, a half or the full width. */
const SIZES = {
  s: "lg:col-span-2",
  m: "lg:col-span-3",
  l: "md:col-span-2 lg:col-span-6",
} as const;
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
/** A faded-ink label that leads to its report (as on Home's money strip). */
const figureLink = "hover:text-foreground hover:underline";
const quietGhost = "text-muted-foreground";

function useLocale(): string {
  const { i18n } = useTranslation();
  return i18n.language || "en-GB";
}

/**
 * Displays a report or widget value: money with its currency, dates in the locale's words
 * (a month group as "Oct 2026"), counts with the locale's separators, otherwise as given.
 */
export function useFormat() {
  const locale = useLocale();
  return (value: unknown, type: string, currency?: string, grain?: string): string => {
    if (value === null || value === undefined || value === "") return "";
    const text = String(value);
    if (type === "money" && currency && /^-?\d+(\.\d+)?$/.test(text)) {
      return formatMoney({ amount: text, currency }, locale);
    }
    if (type === "percent") return `${text}%`;
    if ((type === "date" || type === "text") && ISO_DAY.test(text)) {
      if (grain === "month" || grain === "quarter" || grain === "year") {
        return new Intl.DateTimeFormat(locale, {
          month: grain === "year" ? undefined : "short",
          year: "numeric",
          timeZone: "UTC",
        }).format(new Date(text));
      }
      return formatDate(text, locale);
    }
    if (
      /^-?\d+(\.\d+)?$/.test(text) &&
      (type === "count" || type === "number" || type === "hours")
    ) {
      return new Intl.NumberFormat(locale).format(Number(text));
    }
    return text;
  };
}

/** The period choice as compact filter controls (labels kept for screen readers). */
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
        size="sm"
        hideLabel
        label={t("reporting.period")}
        value={period}
        onChange={(e) => onChange({ period: e.target.value, from, to })}
        options={PRESETS.map((p) => ({ value: p, label: t(`reporting.periods.${p}`) }))}
      />
      {period === "custom" ? (
        <>
          <TextField
            size="sm"
            hideLabel
            type="date"
            label={t("reporting.from")}
            title={t("reporting.from")}
            value={from}
            onChange={(e) => onChange({ period, from: e.target.value, to })}
          />
          <TextField
            size="sm"
            hideLabel
            type="date"
            label={t("reporting.to")}
            title={t("reporting.to")}
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

/** A comparison in words ("Up 20% on the previous period"), or nothing without one. */
function useChange() {
  const { t } = useTranslation();
  return (value: string, previous: string | null): string | null => {
    if (previous === null) return null;
    const now = Number(value);
    const before = Number(previous);
    if (Number.isNaN(now) || Number.isNaN(before)) return null;
    if (before === 0) return t("reporting.noComparison");
    const change = ((now - before) / Math.abs(before)) * 100;
    const rounded = Math.round(change * 10) / 10;
    const key = rounded > 0 ? "reporting.up" : rounded < 0 ? "reporting.down" : "reporting.same";
    return t(key, { percent: Math.abs(rounded) });
  };
}

function reportLink(data: WidgetData): string | null {
  if (!data.widget.report) return null;
  const search = new URLSearchParams(data.report_params as Record<string, string>);
  return `/analytics/${data.widget.report}?${search.toString()}`;
}

/** Splits figures into ruled strips of at most four, as even as possible. */
function stripRows<T>(figures: T[]): T[][] {
  if (figures.length <= 5) return [figures];
  const rows = Math.ceil(figures.length / 4);
  const per = Math.ceil(figures.length / rows);
  const out: T[][] = [];
  for (let i = 0; i < figures.length; i += per) out.push(figures.slice(i, i + per));
  return out;
}

/** A list widget (outstanding, cash forecast, people counts) as a ruled panel. */
function ListWidget({
  data,
  item,
  editing,
}: {
  data: WidgetData;
  item: LayoutItem;
  editing: boolean;
}) {
  const { t } = useTranslation();
  const format = useFormat();
  const href = reportLink(data);
  const title = data.widget.title;
  return (
    <RuledPanel
      title={title}
      flush
      className={SIZES[item.size ?? "s"]}
      aside={
        href && !editing ? (
          <a
            href={href}
            className="text-link hover:underline"
            aria-label={t("reporting.openReportFor", { name: title })}
          >
            {t("reporting.openReport")}
          </a>
        ) : null
      }
    >
      {data.rows.length ? (
        <PanelRows>
          {data.rows.map((r, i) => (
            <PanelRow key={i} className="flex items-baseline justify-between gap-3">
              <span className="min-w-0">{r.label}</span>
              <span className="text-right tabular-nums whitespace-nowrap">
                {data.unit === "money" && r.detail ? format(r.value, "money", r.detail) : r.value}
                {data.unit !== "money" && r.detail ? (
                  <span className="block text-xs text-muted-foreground">{r.detail}</span>
                ) : null}
              </span>
            </PanelRow>
          ))}
        </PanelRows>
      ) : (
        <PanelEmpty>{t("reporting.nothing")}</PanelEmpty>
      )}
    </RuledPanel>
  );
}

/** A chart widget (revenue trend) in a ruled panel, with its numbers under "Show as a table". */
function ChartWidget({
  data,
  item,
  editing,
}: {
  data: WidgetData;
  item: LayoutItem;
  editing: boolean;
}) {
  const { t } = useTranslation();
  const locale = useLocale();
  const href = reportLink(data);
  const title = data.widget.title;
  const series = data.series;
  const keys = series.length ? Object.keys(series[0]?.y ?? {}) : [];
  const currencies = new Set(series.map((p) => p.currency).filter(Boolean));
  const rows = series.map((p) => ({
    x: [ISO_DAY.test(p.x) ? formatDate(p.x, locale) : p.x, currencies.size > 1 ? p.currency : ""]
      .filter(Boolean)
      .join(" "),
    currency: p.currency ?? "",
    ...Object.fromEntries(Object.entries(p.y).map(([k, v]) => [k, Number(v)])),
  }));
  return (
    <RuledPanel
      title={title}
      className={SIZES[item.size ?? "l"]}
      aside={
        href && !editing ? (
          <a
            href={href}
            className="text-link hover:underline"
            aria-label={t("reporting.openReportFor", { name: title })}
          >
            {t("reporting.openReport")}
          </a>
        ) : null
      }
    >
      {rows.length ? (
        <Chart
          kind="line"
          label={title}
          xLabel={t("reporting.date")}
          data={rows}
          series={keys.map((k) => ({ key: k, label: t(`reporting.series.${k}`) }))}
          height={200}
          formatValue={(value, _key, row) =>
            data.unit === "money" && row.currency
              ? formatMoney({ amount: String(value), currency: String(row.currency) }, locale)
              : new Intl.NumberFormat(locale).format(value)
          }
        />
      ) : (
        <p className="text-sm text-muted-foreground">{t("reporting.nothing")}</p>
      )}
    </RuledPanel>
  );
}

/**
 * The customisable figures below Home (FR-26-1). Single figures read as ruled strips with
 * their comparison in words (never tiles); lists and charts are ruled panels. `hide` drops
 * widgets Home already shows (its money strip and register), except while customising, when
 * every widget stays arrangeable.
 */
export function Dashboard({ hide = [] }: { hide?: readonly string[] } = {}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const format = useFormat();
  const change = useChange();
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
  const query = {
    ...periodQuery(period),
    compare: compare as (typeof COMPARISONS)[number],
  };
  const items = editing
    ? draft
    : (layout.data?.widgets ?? []).filter((w) => !hide.includes(w.widget));
  const widgets = useQueries({
    queries: items.map((item) => ({
      queryKey: ["widget", item.widget, query],
      queryFn: async () =>
        unwrap(
          await api.GET("/api/v1/reporting/widgets/{key}", {
            params: { path: { key: item.widget }, query },
          }),
        ),
    })),
  });
  const titles = Object.fromEntries((library.data ?? []).map((w: WidgetInfo) => [w.key, w.title]));
  const move = (index: number, by: number) => {
    const next = [...draft];
    const [item] = next.splice(index, 1);
    if (item) next.splice(index + by, 0, item);
    setDraft(next);
  };

  const loading = !layout.data || widgets.some((w) => w.isPending);
  const figures: StripFigure[] = [];
  const panels: ReactNode[] = [];
  items.forEach((item, index) => {
    const result = widgets[index];
    const data = result?.data;
    if (!data) {
      if (result?.isError) {
        figures.push({
          key: item.widget,
          label: titles[item.widget] ?? item.widget,
          value: "–",
          note: t("reporting.widgetError"),
          tone: "danger",
        });
      }
      return;
    }
    const title = data.widget.title;
    if (data.series.length || data.widget.kind === "chart") {
      panels.push(<ChartWidget key={item.widget} data={data} item={item} editing={editing} />);
      return;
    }
    if (data.rows.length || data.widget.kind === "list") {
      panels.push(<ListWidget key={item.widget} data={data} item={item} editing={editing} />);
      return;
    }
    const href = reportLink(data);
    const named =
      href && !editing ? (
        <a
          href={href}
          className={figureLink}
          aria-label={t("reporting.openReportFor", { name: title })}
        >
          {title}
        </a>
      ) : (
        title
      );
    if (!data.values.length) {
      figures.push({ key: item.widget, label: named, value: "–", note: t("reporting.nothing") });
      return;
    }
    data.values.forEach((v, i) => {
      const single = data.values.length === 1;
      const comparison = change(v.value, v.previous);
      const note = [single && v.label ? v.label : null, comparison].filter(Boolean).join(" · ");
      figures.push({
        key: `${item.widget}-${i}`,
        label: i === 0 ? named : v.label,
        value: format(v.value, data.unit, v.currency),
        note: note || undefined,
      });
    });
  });

  return (
    <section aria-labelledby="dashboard-title" className="space-y-4 border-t border-border pt-6">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <h2 id="dashboard-title" className="text-base font-semibold">
          {t("reporting.dashboard")}
        </h2>
        <div className="flex flex-wrap items-start gap-2">
          <PeriodFields {...period} onChange={setPeriod} />
          <SelectField
            size="sm"
            hideLabel
            label={t("reporting.compare")}
            value={compare}
            onChange={(e) => setCompare(e.target.value)}
            options={COMPARISONS.map((c) => ({
              value: c,
              label: t(`reporting.comparisons.${c}`),
            }))}
          />
          {!editing && layout.data ? (
            <Button
              size="sm"
              variant="secondary"
              className="h-9"
              onClick={() => {
                setDraft(layout.data.widgets);
                setEditing(true);
              }}
            >
              {t("reporting.customise")}
            </Button>
          ) : null}
        </div>
      </div>
      {editing ? (
        <RuledPanel
          title={t("designS9a.arrange")}
          description={t("designS9a.arrangeHelp")}
          flush
          footer={
            <>
              {layout.data?.customised ? (
                <Button size="sm" variant="secondary" onClick={() => reset.mutate()}>
                  {t("reporting.resetLayout")}
                </Button>
              ) : null}
              <Button size="sm" onClick={() => save.mutate(draft)} loading={save.isPending}>
                {t("reporting.saveLayout")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className={quietGhost}
                onClick={() => setEditing(false)}
              >
                {t("common.cancel")}
              </Button>
            </>
          }
        >
          <PanelRows>
            {draft.map((item, index) => {
              const name = titles[item.widget] ?? item.widget;
              return (
                <PanelRow
                  key={item.widget}
                  className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2"
                >
                  <span className="font-medium">{name}</span>
                  <span className="flex flex-wrap items-center gap-2">
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
                      disabled={index === draft.length - 1}
                      onClick={() => move(index, 1)}
                      aria-label={t("reporting.moveLater", { name })}
                    >
                      {t("reporting.later")}
                    </Button>
                    <SelectField
                      size="sm"
                      hideLabel
                      className="h-8"
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
                      variant="ghost"
                      className={quietGhost}
                      onClick={() => setDraft(draft.filter((_, i) => i !== index))}
                      aria-label={t("reporting.remove", { name })}
                    >
                      {t("reporting.removeShort")}
                    </Button>
                  </span>
                </PanelRow>
              );
            })}
            <PanelRow className="flex flex-wrap items-start gap-2">
              <SelectField
                size="sm"
                hideLabel
                label={t("reporting.addWidget")}
                value={adding}
                onChange={(e) => setAdding(e.target.value)}
                options={[
                  { value: "", label: t("designS9a.addFigure") },
                  ...(library.data ?? [])
                    .filter((w) => !draft.some((d) => d.widget === w.key))
                    .map((w) => ({ value: w.key, label: w.title })),
                ]}
              />
              <Button
                size="sm"
                variant="secondary"
                className="h-9"
                disabled={!adding}
                onClick={() => {
                  const info = library.data?.find((w) => w.key === adding);
                  setDraft([
                    ...draft,
                    { widget: adding, size: (info?.default_size ?? "s") as "s" },
                  ]);
                  setAdding("");
                }}
              >
                {t("reporting.add")}
              </Button>
            </PanelRow>
          </PanelRows>
          {save.isError ? (
            <div className="px-5 pb-4">
              <Alert tone="danger">{fieldErrors(save.error).widgets}</Alert>
            </div>
          ) : null}
        </RuledPanel>
      ) : null}
      {loading ? (
        <div aria-busy="true" className="space-y-4">
          <span role="status" className="sr-only">
            {t("grid.loading")}
          </span>
          <div aria-hidden="true" className="flex gap-6 border-y border-border py-4">
            <div className="h-14 w-40 animate-pulse rounded bg-muted" />
            <div className="h-14 w-40 animate-pulse rounded bg-muted" />
            <div className="h-14 w-40 animate-pulse rounded bg-muted" />
          </div>
        </div>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("reporting.emptyDashboard")}</p>
      ) : (
        <>
          {figures.length ? (
            <div aria-label={t("designS9a.figures")} role="group">
              {stripRows(figures).map((row, i) => (
                <FigureStrip key={i} figures={row} className={i ? "-mt-px" : undefined} />
              ))}
            </div>
          ) : null}
          {panels.length ? (
            <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 md:grid-cols-2 lg:grid-cols-6">
              {panels}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

// --- report library -------------------------------------------------------------------------

/** The reports area's own pages, as a row of links ruled like tabs. */
export function ReportsNav() {
  const { t } = useTranslation();
  const canBuild = usePermission("reporting.builder.use");
  const links = [
    { to: "/analytics", label: t("reporting.library") },
    { to: "/analytics/saved", label: t("reporting.savedTitle") },
    ...(canBuild ? [{ to: "/analytics/builder", label: t("reportBuilder.nav") }] : []),
    { to: "/analytics/warehouse", label: t("warehouse.navLink") },
  ] as const;
  return (
    <nav
      aria-label={t("reporting.sections")}
      className="relative mb-6 flex gap-1 overflow-x-auto border-b border-border [scrollbar-width:none]"
    >
      {links.map((l) => (
        <Link
          key={l.to}
          to={l.to}
          activeOptions={{ exact: true }}
          className="-mb-px shrink-0 border-b-2 border-transparent px-3 py-2 text-sm whitespace-nowrap text-muted-foreground hover:text-foreground [&.active]:border-foreground [&.active]:font-semibold [&.active]:text-foreground"
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}

/** A page of the reports area: the page header, then the area's row of links. */
export function ReportsPage({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div>
      <PageHeader title={title} description={description} actions={actions} className="mb-4" />
      <ReportsNav />
      <div className="space-y-6">{children}</div>
    </div>
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
    <ReportsPage title={t("reporting.title")} description={t("designS9a.libraryHelp")}>
      {reports.isPending ? (
        <RuledPanel label={t("reporting.title")} flush>
          <PanelLoading label={t("grid.loading")} />
        </RuledPanel>
      ) : null}
      {reports.data?.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("reporting.noReports")}</p>
      ) : null}
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 xl:grid-cols-2">
        {groups.map(([key, group]) => (
          <RuledPanel
            key={key}
            title={group.label}
            titleId={`cat-${key}`}
            flush
            aside={
              <span className="text-muted-foreground tabular-nums">
                {t("designS9a.reportCount", { count: group.items.length })}
              </span>
            }
          >
            <PanelRows>
              {group.items.map((r) => (
                <li key={r.key} className="relative px-5 py-2.5 text-sm hover:bg-muted/60">
                  <a
                    href={`/analytics/${r.key}`}
                    className="font-medium after:absolute after:inset-0 hover:underline"
                  >
                    {r.title}
                  </a>
                  <p className="text-xs text-muted-foreground">{r.description}</p>
                </li>
              ))}
            </PanelRows>
          </RuledPanel>
        ))}
      </div>
    </ReportsPage>
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
      size="sm"
      hideLabel
      label={t(`reporting.filters.${filter}`)}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      options={[{ value: "", label: t(`designS9a.any.${filter}`) }, ...(options.data ?? [])]}
    />
  );
}

// Gap G5: custom-field filters on clients, students or tutors (``[entity.]key=value``).
const ENTITY_TYPES: Record<string, string> = {
  client: "people.client",
  student: "people.student",
  tutor: "people.tutor",
};

function parseCustomField(raw: string, fallback: string) {
  const [left = "", ...rest] = raw.split("=");
  const dot = left.indexOf(".");
  return dot < 0
    ? { entity: raw ? "client" : fallback, key: left, value: rest.join("=") }
    : { entity: left.slice(0, dot), key: left.slice(dot + 1), value: rest.join("=") };
}

function CustomFieldFilter({
  entities,
  value,
  onChange,
  hintId,
  onKeyChange,
}: {
  entities: string[];
  value: string;
  onChange: (v: string) => void;
  /** The shared hint line under the filter row. */
  hintId: string;
  onKeyChange: (chosen: boolean) => void;
}) {
  const { t } = useTranslation();
  const initial = parseCustomField(value, entities[0] ?? "client");
  const [entity, setEntity] = useState(
    entities.includes(initial.entity) ? initial.entity : (entities[0] ?? "client"),
  );
  const [key, setKey] = useState(initial.key);
  const [text, setText] = useState(initial.value);
  const fields = useQuery({
    queryKey: ["custom-fields", entity],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/custom-fields", {
          params: { query: { entity_type: ENTITY_TYPES[entity] ?? entity } },
        }),
      ),
  });
  const apply = (e: string, k: string, v: string) =>
    onChange(k && v.trim() ? `${e}.${k}=${v.trim()}` : "");
  const entityName = t(`reportingG5.entities.${entity}`);
  return (
    <fieldset className="flex min-w-0 flex-wrap items-start gap-2">
      <legend className="sr-only">{t("reportingG5.customFieldFilter")}</legend>
      {entities.length > 1 ? (
        <SelectField
          size="sm"
          hideLabel
          label={t("reportingG5.customFieldOf")}
          value={entity}
          onChange={(e) => {
            setEntity(e.target.value);
            setKey("");
            onKeyChange(false);
            apply(e.target.value, "", text);
          }}
          options={entities.map((v) => ({
            value: v,
            label: t("designS9a.fieldsOf", { entity: t(`reportingG5.entities.${v}`) }),
          }))}
        />
      ) : null}
      <SelectField
        size="sm"
        hideLabel
        label={t("reportingG5.customField", { entity: entityName })}
        value={key}
        onChange={(e) => {
          setKey(e.target.value);
          onKeyChange(Boolean(e.target.value));
          apply(entity, e.target.value, text);
        }}
        options={[
          { value: "", label: t("designS9a.anyField", { entity: entityName }) },
          ...(fields.data ?? [])
            .filter((f) => f.active !== false)
            .map((f) => ({ value: f.key, label: f.label })),
        ]}
      />
      {key ? (
        <TextField
          size="sm"
          hideLabel
          label={t("reportingG5.customFieldValue")}
          placeholder={t("designS9a.equals")}
          aria-describedby={hintId}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => apply(entity, key, text)}
          onKeyDown={(e) => {
            if (e.key === "Enter") apply(entity, key, text);
          }}
        />
      ) : null}
    </fieldset>
  );
}

/** The grain of a grouped date column: "month" for `group` by month or `date:month`. */
function grainOf(col: Column, params: Record<string, unknown> | undefined): string | undefined {
  const [, grain] = col.key.split(":");
  if (grain) return grain;
  if (col.key === "group" && typeof params?.group_by === "string") return params.group_by;
  return undefined;
}

const FIGURE_TYPES = new Set(["money", "count", "number", "hours", "percent"]);

/**
 * A report's rows as a register table: figure columns right-aligned and tabular (money in a
 * fixed 8rem amount column), totals in the footer under the figures they add up. On phones
 * the currency column folds away (each amount carries its own symbol) and a wide table
 * scrolls inside its labelled region under a one-line hint.
 */
export function ResultTable({
  result,
  caption,
}: {
  result: Pick<Result, "columns" | "rows" | "totals"> & { params?: unknown };
  caption: string;
}) {
  const { t } = useTranslation();
  const format = useFormat();
  const phone = useIsPhone();
  const rows = result.rows as Cell[];
  const totals = result.totals as Cell[];
  const params = result.params as Record<string, unknown> | undefined;
  const hasMoney = result.columns.some((c) => c.type === "money");
  const cols = result.columns.filter((c) => !(phone && hasMoney && c.key === "currency"));
  const figure = (c: Column) => FIGURE_TYPES.has(c.type);
  const show = (col: Column, row: Cell) =>
    format(
      row[col.key],
      col.type,
      typeof row.currency === "string" ? row.currency : undefined,
      grainOf(col, params),
    );
  const columns: RuledColumn[] = cols.map((c, i) => ({
    key: c.key,
    header: c.label,
    end: figure(c),
    width: c.type === "money" ? "w-32" : i === 0 ? "min-w-36" : undefined,
  }));
  return (
    <>
      {phone && cols.length > 3 && rows.length ? (
        <p className="px-5 pt-3 text-xs text-muted-foreground">{t("designS9a.scrollHint")}</p>
      ) : null}
      <RuledTable
        caption={caption}
        columns={columns}
        empty={rows.length === 0 ? t("reporting.nothing") : undefined}
        footer={
          totals.length
            ? totals.map((row, i) => (
                <tr key={i} className={cn("font-semibold", i > 0 && "border-t border-rule")}>
                  {cols.map((c, j) => (
                    <td key={c.key} className={figure(c) ? figureCell : undefined}>
                      {j === 0 ? t("reporting.total") : c.key in row ? show(c, row) : ""}
                    </td>
                  ))}
                </tr>
              ))
            : undefined
        }
      >
        {rows.map((row, i) => (
          <tr key={i}>
            {cols.map((c) => (
              <td key={c.key} className={figure(c) ? figureCell : undefined}>
                {show(c, row)}
              </td>
            ))}
          </tr>
        ))}
      </RuledTable>
    </>
  );
}

/**
 * A run report in one flush ruled panel: the period it covers as the title, the row count as
 * the aside, the chart (in link ink) above the table, notes, and a footer for its actions.
 */
export function ResultPanel({
  result,
  title,
  aside,
  footer,
}: {
  result: Pick<
    Result,
    "columns" | "rows" | "totals" | "chart" | "notes" | "period" | "generated_at"
  > & { params?: unknown };
  title: string;
  aside?: ReactNode;
  footer?: ReactNode;
}) {
  const { t } = useTranslation();
  const locale = useLocale();
  const format = useFormat();
  const chart = result.chart;
  const columns = result.columns;
  const params = result.params as Record<string, unknown> | undefined;
  const xCol = chart ? columns.find((c) => c.key === chart.x) : undefined;
  const currencies = new Set(
    (result.rows as Cell[]).map((r) => (typeof r.currency === "string" ? r.currency : "")),
  );
  const chartData =
    chart && xCol
      ? (result.rows as Cell[]).map((row) => ({
          x: [
            format(row[chart.x], xCol.type, undefined, grainOf(xCol, params)),
            currencies.size > 1 && typeof row.currency === "string" ? row.currency : "",
          ]
            .filter(Boolean)
            .join(" "),
          currency: typeof row.currency === "string" ? row.currency : "",
          ...Object.fromEntries(chart.y.map((k) => [k, Number(row[k] ?? 0)])),
        }))
      : [];
  const types = Object.fromEntries(columns.map((c) => [c.key, c.type]));
  const labels = Object.fromEntries(columns.map((c) => [c.key, c.label]));
  const period = result.period
    ? t("reporting.showing", {
        from: formatDate(String(result.period.from), locale),
        to: formatDate(String(result.period.to), locale),
      })
    : t("designS9a.asAt", { date: formatDate(String(result.generated_at), locale) });
  return (
    <RuledPanel
      title={period}
      flush
      aside={
        aside ?? (
          <span className="text-muted-foreground tabular-nums">
            {t("reporting.rows", { count: result.rows.length })}
          </span>
        )
      }
      footer={footer}
    >
      {chart && chartData.length ? (
        <div className="border-b border-border px-5 py-4">
          <Chart
            kind={chart.kind}
            data={chartData as Array<Record<string, string | number>>}
            series={chart.y.map((k) => ({ key: k, label: labels[k] ?? k }))}
            label={t("reporting.chartOf", { name: title })}
            xLabel={labels[chart.x] ?? chart.x}
            stacked={chart.stacked}
            srTable={false}
            formatValue={(value, key, row) =>
              format(String(value), types[key] ?? "number", String(row.currency ?? ""))
            }
          />
        </div>
      ) : null}
      <ResultTable result={result} caption={title} />
      {result.notes.length ? (
        <div className="space-y-1 border-t border-rule px-5 py-3 text-xs text-muted-foreground">
          {result.notes.map((n) => (
            <p key={n}>{n}</p>
          ))}
        </div>
      ) : null}
    </RuledPanel>
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
      className="flex w-full flex-wrap items-start gap-x-3 gap-y-2"
      aria-label={t("reporting.saveView")}
    >
      <div className="w-full sm:w-56">
        <TextField
          size="sm"
          hideLabel
          label={t("reporting.viewName")}
          placeholder={t("reporting.viewName")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={errors.name}
          required
        />
      </div>
      <label className="flex h-9 items-center gap-2 text-sm">
        <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
        {t("reporting.shareView")}
      </label>
      <Button
        type="submit"
        size="sm"
        variant="secondary"
        className="h-9"
        loading={save.isPending}
      >
        {t("reporting.saveView")}
      </Button>
      {save.isSuccess ? (
        <p role="status" className="flex h-9 items-center text-success">
          {t("reporting.viewSaved")}
        </p>
      ) : null}
    </form>
  );
}

export function ReportViewPage({ reportKey }: { reportKey: string }) {
  const { t } = useTranslation();
  const canExport = usePermission("reporting.export");
  const hintId = useId();
  const initial = useMemo(initialParams, []);
  const [params, setParams] = useState<Record<string, string>>(initial);
  const [currency, setCurrency] = useState(initial.currency ?? "");
  const [fieldChosen, setFieldChosen] = useState(Boolean(initial.custom_field));
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
  return (
    <div>
      <RecordHeader
        back={<a href="/analytics">{t("reporting.library")}</a>}
        title={title}
        description={def?.description}
        actions={
          canExport && result ? (
            <div
              role="group"
              aria-label={t("reporting.export")}
              className="flex flex-wrap items-center gap-2"
            >
              <span className="text-sm text-muted-foreground">{t("reporting.export")}</span>
              {(["csv", "xlsx", "pdf"] as const).map((fmt) => (
                <a
                  key={fmt}
                  href={exportHref(fmt)}
                  className={buttonClass({ variant: "secondary", size: "sm" })}
                  download
                >
                  {t(`reporting.formats.${fmt}`)}
                </a>
              ))}
            </div>
          ) : null
        }
      />
      <div className="space-y-6">
        {def ? (
          <form aria-label={t("reporting.filtersLabel")} onSubmit={(e) => e.preventDefault()}>
            <div className="flex flex-wrap items-start gap-2">
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
                  size="sm"
                  hideLabel
                  label={t("reporting.groupBy")}
                  value={params.group_by ?? def.group_by[0]?.value ?? ""}
                  onChange={(e) => set({ group_by: e.target.value })}
                  options={def.group_by.map((g) => ({
                    value: g.value,
                    label: t("designS9a.groupByOption", { name: g.label }),
                  }))}
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
              {def.custom_field_entities?.length ? (
                <CustomFieldFilter
                  entities={def.custom_field_entities}
                  value={params.custom_field ?? ""}
                  onChange={(v) => set({ custom_field: v })}
                  hintId={hintId}
                  onKeyChange={setFieldChosen}
                />
              ) : null}
              <div className="w-44">
                <TextField
                  size="sm"
                  hideLabel
                  label={t("reporting.currency")}
                  placeholder={t("designS9a.currencyPlaceholder")}
                  aria-describedby={hintId}
                  value={currency}
                  maxLength={3}
                  onChange={(e) => {
                    const v = e.target.value.toUpperCase();
                    setCurrency(v);
                    if (v.length === 0 || v.length === 3) set({ currency: v });
                  }}
                />
              </div>
            </div>
            <p id={hintId} className="mt-2 text-xs text-muted-foreground">
              {t("reporting.currencyHint")}
              {fieldChosen ? ` ${t("reportingG5.customFieldHint")}` : ""}
            </p>
          </form>
        ) : null}
        {report.isError ? (
          <Alert tone="danger" title={t("reporting.runError")}>
            {Object.values(errors).join(" ")}
          </Alert>
        ) : null}
        {report.isPending ? (
          <RuledPanel label={title} flush>
            <PanelLoading label={t("grid.loading")} />
          </RuledPanel>
        ) : null}
        {result ? (
          <ResultPanel
            result={result}
            title={title}
            footer={
              <SaveView reportKey={reportKey} params={result.params as Record<string, string>} />
            }
          />
        ) : null}
      </div>
    </div>
  );
}

// --- saved and scheduled reports ------------------------------------------------------------

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

/** Schedule a saved report view or (gap G5) a custom report (``kind: "custom"``), opened in
 * place under the report's row. */
export function ScheduleForm({
  saved,
  onDone,
  onCancel,
  narrow = false,
}: {
  saved: { id: string; name: string; kind?: "saved" | "custom" };
  onDone: () => void;
  onCancel?: () => void;
  /** One field per line (in a side column). */
  narrow?: boolean;
}) {
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
            ...(saved.kind === "custom" ? { custom_report: saved.id } : { saved_report: saved.id }),
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
      className="mt-3 space-y-3 border-t border-rule pt-3"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <div
        className={cn(
          "grid items-start gap-x-4 gap-y-3",
          !narrow && "sm:grid-cols-2 lg:grid-cols-4",
        )}
      >
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
            className="w-24 text-right tabular-nums"
            label={t("reporting.dayOfMonth")}
            value={day}
            onChange={(e) => setDay(e.target.value)}
            error={errors.day_of_month}
          />
        ) : null}
        <TextField
          type="time"
          className="tabular-nums"
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
        <legend className="mb-1 text-sm font-medium">{t("reporting.recipients")}</legend>
        <div className={cn("grid gap-x-4 gap-y-1", !narrow && "sm:grid-cols-2")}>
          {(staff.data ?? []).map((s) => (
            <label key={s.id} className="flex min-w-0 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={recipients.includes(s.id)}
                onChange={(e) =>
                  setRecipients(
                    e.target.checked
                      ? [...recipients, s.id]
                      : recipients.filter((r) => r !== s.id),
                  )
                }
              />
              <span className="min-w-0 break-words">
                {s.name} ({s.email})
              </span>
            </label>
          ))}
        </div>
        {errors.recipients ? (
          <p className="mt-1 text-xs text-danger" role="alert">
            {errors.recipients}
          </p>
        ) : null}
      </fieldset>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" loading={create.isPending}>
          {t("reporting.schedule")}
        </Button>
        {onCancel ? (
          <Button type="button" size="sm" variant="ghost" className={quietGhost} onClick={onCancel}>
            {t("common.cancel")}
          </Button>
        ) : null}
      </div>
    </form>
  );
}

export function SavedReportsPage() {
  const { t } = useTranslation();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const phone = useIsPhone();
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
  const savedRows = saved.data?.results ?? [];
  const scheduledRows = scheduled.data?.results ?? [];
  const runRows = runs.data?.results ?? [];
  return (
    <ReportsPage title={t("reporting.savedTitle")} description={t("designS9a.savedHelp")}>
      <RuledPanel title={t("reporting.savedViews")} titleId="saved-views" flush>
        {saved.isPending ? (
          <PanelLoading label={t("grid.loading")} />
        ) : savedRows.length === 0 ? (
          <PanelEmpty>{t("reporting.noSaved")}</PanelEmpty>
        ) : (
          <PanelRows>
            {savedRows.map((s) => (
              <PanelRow key={s.id}>
                <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
                  <div className="min-w-0">
                    <a href={viewHref(s)} className="font-medium hover:underline">
                      {s.name}
                    </a>
                    <p className="text-xs text-muted-foreground">
                      {s.shared
                        ? t("reporting.sharedBy", { name: s.owner_name })
                        : t("reporting.private")}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {canSchedule && s.is_mine ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        aria-expanded={scheduling === s.id}
                        onClick={() => setScheduling(scheduling === s.id ? null : s.id)}
                      >
                        {t("reporting.scheduleEmail")}
                      </Button>
                    ) : null}
                    {s.is_mine ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className={quietGhost}
                        onClick={() => removeSaved.mutate(s.id)}
                        aria-label={t("reporting.deleteView", { name: s.name })}
                      >
                        {t("reporting.delete")}
                      </Button>
                    ) : null}
                  </div>
                </div>
                {scheduling === s.id ? (
                  <ScheduleForm
                    saved={s}
                    onCancel={() => setScheduling(null)}
                    onDone={() => {
                      setScheduling(null);
                      void queryClient.invalidateQueries({ queryKey: ["scheduled-reports"] });
                    }}
                  />
                ) : null}
              </PanelRow>
            ))}
          </PanelRows>
        )}
      </RuledPanel>
      {canSchedule ? (
        <RuledPanel title={t("reporting.scheduledTitle")} titleId="scheduled" flush>
          {scheduled.isPending ? (
            <PanelLoading label={t("grid.loading")} />
          ) : scheduledRows.length === 0 ? (
            <PanelEmpty>{t("reporting.noScheduled")}</PanelEmpty>
          ) : (
            <PanelRows>
              {scheduledRows.map((s) => (
                <PanelRow
                  key={s.id}
                  className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2"
                >
                  <div className="min-w-0">
                    <p className="font-medium">{s.report_name}</p>
                    <p className="text-xs text-muted-foreground">
                      {[
                        s.enabled ? null : t("designS9a.paused"),
                        s.custom_report ? t("reportingG5.customReport") : null,
                        t(`reporting.frequencies.${s.frequency}`),
                        s.time,
                        t(`reporting.formats.${s.format ?? "csv"}`),
                        s.recipient_details.map((r) => r.name).join(", "),
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button size="sm" variant="secondary" onClick={() => toggle.mutate(s)}>
                      {s.enabled ? t("reporting.pause") : t("reporting.resume")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className={quietGhost}
                      onClick={() => removeScheduled.mutate(s.id)}
                      aria-label={t("reporting.deleteSchedule", { name: s.report_name })}
                    >
                      {t("reporting.delete")}
                    </Button>
                  </div>
                </PanelRow>
              ))}
            </PanelRows>
          )}
        </RuledPanel>
      ) : null}
      {canExport ? (
        <RuledPanel title={t("reporting.runsTitle")} titleId="runs" flush>
          <RuledTable
            caption={t("reporting.runsTitle")}
            loading={runs.isPending}
            loadingLabel={t("grid.loading")}
            empty={!runs.isPending && runRows.length === 0 ? t("designS9a.noRuns") : undefined}
            columns={[
              { key: "report", header: t("designS9a.report"), width: "min-w-40" },
              ...(phone ? [] : [{ key: "when", header: t("designS9a.when") }]),
              { key: "status", header: t("designS9a.status") },
              { key: "rows", header: t("designS9a.rowsHeading"), end: true },
              { key: "actions", header: t("common.actions"), hidden: true },
            ]}
          >
            {runRows.map((r) => (
              <tr key={r.id}>
                <td>
                  <span className="font-medium">{r.saved_report_name ?? r.report_key}</span>
                  {phone ? (
                    <span className="block text-xs text-muted-foreground tabular-nums">
                      {formatDateTime(r.created_at, locale)}
                    </span>
                  ) : null}
                </td>
                {phone ? null : (
                  <td className="whitespace-nowrap tabular-nums">
                    {formatDateTime(r.created_at, locale)}
                  </td>
                )}
                <td className={r.status === "failed" ? "font-medium text-danger" : undefined}>
                  {t(`reporting.runStatus.${r.status}`)}
                </td>
                <td className={figureCell}>{r.row_count}</td>
                <td className="text-right">
                  {r.file_name ? (
                    <Button size="sm" variant="secondary" onClick={() => download.mutate(r)}>
                      {t("reporting.download")}
                    </Button>
                  ) : null}
                </td>
              </tr>
            ))}
          </RuledTable>
        </RuledPanel>
      ) : null}
    </ReportsPage>
  );
}
