import { useTranslation } from "@tutortrack/i18n";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/** Colour-blind-safe palette (Okabe-Ito), distinguishable in light and dark themes. */
const PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00"];

export interface ChartSeries {
  key: string;
  label: string;
}

export interface ChartProps {
  kind: "bar" | "line" | "pie";
  /** One object per category: `{x: "Nia", net: 40}`. */
  data: Array<Record<string, string | number>>;
  series: ChartSeries[];
  /** Accessible name; the data is also given as a table for screen readers. */
  label: string;
  xLabel: string;
  stacked?: boolean;
  height?: number;
  /** Also give the data as a hidden table (off when a visible table follows). */
  srTable?: boolean;
}

/**
 * A chart with a screen-reader table of the same data (WCAG 1.1.1): the drawing is
 * decorative to assistive technology, the table carries the numbers.
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
}: ChartProps) {
  const { t } = useTranslation();
  // jsdom (tests) has no ResizeObserver; the table still renders.
  const canDraw = typeof window !== "undefined" && "ResizeObserver" in window;
  return (
    <figure className="space-y-2" aria-label={label}>
      {canDraw && data.length > 0 ? (
        <div aria-hidden="true" style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            {kind === "pie" ? (
              <PieChart>
                <Pie data={data} dataKey={series[0]?.key ?? "value"} nameKey="x" outerRadius="80%">
                  {data.map((_, i) => (
                    <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            ) : kind === "line" ? (
              <LineChart data={data}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="x" />
                <YAxis />
                <Tooltip />
                <Legend />
                {series.map((s, i) => (
                  <Line
                    key={s.key}
                    dataKey={s.key}
                    name={s.label}
                    stroke={PALETTE[i % PALETTE.length]}
                    strokeWidth={2}
                    dot={false}
                  />
                ))}
              </LineChart>
            ) : (
              <BarChart data={data}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="x" />
                <YAxis />
                <Tooltip />
                <Legend />
                {series.map((s, i) => (
                  <Bar
                    key={s.key}
                    dataKey={s.key}
                    name={s.label}
                    fill={PALETTE[i % PALETTE.length]}
                    stackId={stacked ? "stack" : undefined}
                  />
                ))}
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      ) : null}
      {srTable ? (
        <figcaption className="sr-only">
          <table>
            <caption>{t("reporting.chartData", { name: label })}</caption>
            <thead>
              <tr>
                <th scope="col">{xLabel}</th>
                {series.map((s) => (
                  <th key={s.key} scope="col">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row, i) => (
                <tr key={i}>
                  <th scope="row">{row.x}</th>
                  {series.map((s) => (
                    <td key={s.key}>{row[s.key]}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </figcaption>
      ) : null}
    </figure>
  );
}
