import { useTranslation } from "@tutortrack/i18n";
import { cn, Disclosure, figureCell, RuledTable } from "@tutortrack/ui";
import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * Charts draw in link ink, never the tenant colour (the Tenant Fills, the Register Inks
 * Rule). Series are told apart by strength and, for lines, by dash, so colour is never the
 * only cue; a legend names them and the numbers are always available as a table.
 */
const STRENGTH = [1, 0.55, 0.3, 0.16];
const DASH = [undefined, "6 4", "2 3", "8 3 2 3"];
/** Axis text, grid and cursor take the register's tokens through CSS (it beats SVG attributes). */
const SKIN = cn(
  "text-link",
  "[&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground [&_.recharts-cartesian-axis-tick_text]:text-xs",
  "[&_.recharts-cartesian-grid_line]:stroke-rule",
  "[&_.recharts-text]:tabular-nums",
);

export interface ChartSeries {
  key: string;
  label: string;
}

export interface ChartProps {
  kind: "bar" | "line" | "pie";
  /** One object per category: `{x: "Nia", net: 40}`. */
  data: Array<Record<string, string | number>>;
  series: ChartSeries[];
  /** Accessible name of the figure. */
  label: string;
  xLabel: string;
  stacked?: boolean;
  height?: number;
  /** Offer the numbers as a table under a "Show as a table" disclosure (off when a visible
   * table of the same data follows the chart). */
  srTable?: boolean;
  /** Writes a value for the tooltip, the table and the axis (money with its currency). */
  formatValue?: (value: number, seriesKey: string, row: Record<string, string | number>) => string;
}

function strength(i: number): number {
  return STRENGTH[i % STRENGTH.length] ?? 1;
}

function Swatch({ kind, index }: { kind: ChartProps["kind"]; index: number }) {
  if (kind === "line") {
    return (
      <svg width="20" height="8" aria-hidden="true" className="shrink-0 text-link">
        <line
          x1="0"
          x2="20"
          y1="4"
          y2="4"
          stroke="currentColor"
          strokeWidth="2"
          strokeDasharray={DASH[index % DASH.length]}
          strokeOpacity={index >= DASH.length ? strength(index) : 1}
        />
      </svg>
    );
  }
  return (
    <svg width="10" height="10" aria-hidden="true" className="shrink-0 text-link">
      <rect width="10" height="10" rx="2" fill="currentColor" fillOpacity={strength(index)} />
    </svg>
  );
}

function Legend({ items }: { items: Array<{ key: string; label: ReactNode; swatch: ReactNode }> }) {
  return (
    <ul aria-hidden="true" className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {items.map((item) => (
        <li key={item.key} className="flex items-center gap-1.5">
          {item.swatch}
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/** The tooltip: a small clean leaf with a register-rule edge and no shadow. */
function Tip({
  active,
  payload,
  label,
  format,
}: {
  active?: boolean;
  payload?: Array<{
    name?: string;
    value?: number | string;
    dataKey?: string | number;
    payload?: Record<string, string | number>;
  }>;
  label?: string | number;
  format: (value: number, key: string, row: Record<string, string | number>) => string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload ?? {};
  return (
    <div className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-foreground">
      <p className="font-medium">{label ?? row.x}</p>
      {payload.map((p) => (
        <p key={String(p.dataKey ?? p.name)} className="tabular-nums">
          {payload.length > 1 || p.name !== undefined ? `${p.name}: ` : ""}
          {format(Number(p.value ?? 0), String(p.dataKey ?? ""), p.payload ?? row)}
        </p>
      ))}
    </div>
  );
}

/**
 * A chart of report figures. The drawing takes its width from its container, so its 12px
 * text stays 12px on phones; the drawing itself is hidden from assistive technology, and the
 * same numbers are a table (under "Show as a table", or the report's own table).
 */
export function Chart({
  kind,
  data,
  series,
  label,
  xLabel,
  stacked,
  height = 240,
  srTable = true,
  formatValue,
}: ChartProps) {
  const { t, i18n } = useTranslation();
  // jsdom (tests) has no ResizeObserver; the table still renders.
  const canDraw = typeof window !== "undefined" && "ResizeObserver" in window;
  const plain = new Intl.NumberFormat(i18n.language || "en-GB");
  const compact = new Intl.NumberFormat(i18n.language || "en-GB", {
    notation: "compact",
    maximumFractionDigits: 1,
  });
  const format = formatValue ?? ((value: number) => plain.format(value));
  const tip = (props: object) => <Tip {...(props as Parameters<typeof Tip>[0])} format={format} />;
  const axis = { axisLine: false, tickLine: false, tickMargin: 6 } as const;
  const legendItems =
    kind === "pie"
      ? data.map((row, i) => ({
          key: `${row.x}-${i}`,
          label: String(row.x),
          swatch: <Swatch kind="pie" index={i} />,
        }))
      : series.length > 1
        ? series.map((s, i) => ({ key: s.key, label: s.label, swatch: <Swatch kind={kind} index={i} /> }))
        : [];
  return (
    <figure className="min-w-0 space-y-3" aria-label={label}>
      {canDraw && data.length > 0 ? (
        <div aria-hidden="true" className={SKIN} style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            {kind === "pie" ? (
              <PieChart>
                <Pie
                  data={data}
                  dataKey={series[0]?.key ?? "value"}
                  nameKey="x"
                  outerRadius="85%"
                  innerRadius="45%"
                  isAnimationActive={false}
                  stroke="hsl(var(--tt-surface))"
                  strokeWidth={2}
                >
                  {data.map((_, i) => (
                    <Cell key={i} fill="currentColor" fillOpacity={strength(i)} />
                  ))}
                </Pie>
                <Tooltip content={tip} />
              </PieChart>
            ) : kind === "line" ? (
              <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="x" {...axis} minTickGap={24} interval="preserveStartEnd" />
                <YAxis {...axis} width={48} tickFormatter={(v: number) => compact.format(v)} />
                <Tooltip
                  content={tip}
                  cursor={{ stroke: "currentColor", strokeOpacity: 0.3 }}
                  isAnimationActive={false}
                />
                {series.map((s, i) => (
                  <Line
                    key={s.key}
                    dataKey={s.key}
                    name={s.label}
                    stroke="currentColor"
                    strokeWidth={2}
                    strokeDasharray={DASH[i % DASH.length]}
                    strokeOpacity={i >= DASH.length ? strength(i) : 1}
                    dot={data.length <= 12 ? { r: 3, fill: "currentColor", strokeWidth: 0 } : false}
                    activeDot={{ r: 5, fill: "currentColor", stroke: "hsl(var(--tt-surface))", strokeWidth: 2 }}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            ) : (
              <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="x" {...axis} minTickGap={12} interval="preserveStartEnd" />
                <YAxis {...axis} width={48} tickFormatter={(v: number) => compact.format(v)} />
                <Tooltip
                  content={tip}
                  cursor={{ fill: "currentColor", fillOpacity: 0.08 }}
                  isAnimationActive={false}
                />
                {series.map((s, i) => (
                  <Bar
                    key={s.key}
                    dataKey={s.key}
                    name={s.label}
                    fill="currentColor"
                    fillOpacity={strength(i)}
                    stroke={stacked ? "hsl(var(--tt-surface))" : undefined}
                    maxBarSize={56}
                    radius={stacked ? 0 : [2, 2, 0, 0]}
                    stackId={stacked ? "stack" : undefined}
                    isAnimationActive={false}
                  />
                ))}
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      ) : null}
      {legendItems.length ? <Legend items={legendItems} /> : null}
      {srTable ? (
        <Disclosure summary={t("designS9a.showTable")}>
          <RuledTable
            caption={t("reporting.chartData", { name: label })}
            columns={[
              { key: "x", header: xLabel },
              ...series.map((s) => ({ key: s.key, header: s.label, end: true })),
            ]}
            className="rounded-md border border-border"
          >
            {data.map((row, i) => (
              <tr key={i}>
                <th scope="row" className="py-2.5 font-normal">
                  {row.x}
                </th>
                {series.map((s) => (
                  <td key={s.key} className={figureCell}>
                    {format(Number(row[s.key] ?? 0), s.key, row)}
                  </td>
                ))}
              </tr>
            ))}
          </RuledTable>
        </Disclosure>
      ) : null}
    </figure>
  );
}
