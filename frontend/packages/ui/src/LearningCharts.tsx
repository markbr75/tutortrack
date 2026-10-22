import { useEffect, useId, useRef, useState } from "react";

import { cn } from "./cn";
import { MASTERY_LEVELS, type MasteryLevel } from "./masteryLevels";

export type { MasteryLevel };

export interface TrendPoint {
  date: string;
  percent: string;
  name: string;
  grade?: string;
}

export interface TrendChartLabels {
  title: string;
  date: string;
  assessment: string;
  score: string;
  showTable: string;
  empty: string;
}

/** The drawing width follows the container (up to 672px), so 12px labels stay 12px on phones. */
const MAX_W = 672;
const H = 220;
const PAD = { top: 12, right: 16, bottom: 28, left: 40 };
const TICKS = [0, 25, 50, 75, 100];

/** Score % over time: one 2px line in link ink (never the tenant colour), focusable 8px markers with a
 * tooltip, a recessive grid on one 0-100 axis and a table view (WCAG 2.2 AA). */
export function TrendChart({
  points,
  labels,
  formatDate,
  hideTitle = false,
}: {
  points: ReadonlyArray<TrendPoint>;
  labels: TrendChartLabels;
  formatDate: (iso: string) => string;
  /** Keep the caption for screen readers only, when a panel heading already names it. */
  hideTitle?: boolean;
}) {
  const titleId = useId();
  const [active, setActive] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const hasPoints = points.length > 0;
  const [W, setW] = useState(320);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const width = Math.round(el.getBoundingClientRect().width);
      if (width > 0) setW(Math.min(Math.max(width, 240), MAX_W));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasPoints]);
  if (!points.length) {
    return (
      <div ref={box}>
        <p className="text-sm text-muted-foreground">{labels.empty}</p>
      </div>
    );
  }
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const times = points.map((p) => new Date(p.date).getTime());
  const first = Math.min(...times);
  const span = Math.max(...times) - first || 1;
  const x = (i: number) =>
    PAD.left + (points.length === 1 ? innerW / 2 : ((times[i]! - first) / span) * innerW);
  const y = (pct: number) => PAD.top + innerH - (Math.min(Math.max(pct, 0), 100) / 100) * innerH;
  const path = points
    .map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(Number(p.percent)).toFixed(1)}`)
    .join(" ");
  const shown = active !== null ? points[active] : null;
  return (
    <figure className="space-y-2">
      <figcaption id={titleId} className={hideTitle ? "sr-only" : "text-sm font-semibold"}>
        {labels.title}
      </figcaption>
      <div ref={box} className="relative max-w-2xl overflow-hidden">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width={W}
          height={H}
          className="block"
          role="img"
          aria-labelledby={titleId}
        >
          {TICKS.map((tick) => (
            <g key={tick}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(tick)}
                y2={y(tick)}
                className="stroke-border"
                strokeWidth={1}
              />
              <text
                x={PAD.left - 6}
                y={y(tick) + 4}
                textAnchor="end"
                className="fill-muted-foreground text-xs"
              >
                {tick}%
              </text>
            </g>
          ))}
          <path d={path} fill="none" className="stroke-link" strokeWidth={2} />
          {points.map((p, i) => (
            <circle
              key={`${p.date}-${i}`}
              cx={x(i)}
              cy={y(Number(p.percent))}
              r={active === i ? 6 : 4}
              className="fill-link stroke-surface"
              strokeWidth={2}
              tabIndex={0}
              role="button"
              aria-label={`${p.name}, ${formatDate(p.date)}: ${p.percent}%`}
              onMouseEnter={() => setActive(i)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
            />
          ))}
          <text x={PAD.left} y={H - 6} className="fill-muted-foreground text-xs">
            {formatDate(points[0]!.date)}
          </text>
          {points.length > 1 ? (
            <text
              x={W - PAD.right}
              y={H - 6}
              textAnchor="end"
              className="fill-muted-foreground text-xs"
            >
              {formatDate(points[points.length - 1]!.date)}
            </text>
          ) : null}
        </svg>
        {shown ? (
          <div
            role="status"
            className="pointer-events-none absolute left-2 top-2 rounded-md border border-border bg-surface px-2 py-1 text-xs shadow"
          >
            <p className="font-medium">{shown.name}</p>
            <p>
              {formatDate(shown.date)} · {shown.percent}%{shown.grade ? ` · ${shown.grade}` : ""}
            </p>
          </div>
        ) : null}
      </div>
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm font-medium text-link [&::-webkit-details-marker]:hidden">
          <svg
            viewBox="0 0 24 24"
            aria-hidden="true"
            className="size-3.5 transition-transform duration-150 group-open:rotate-90"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.75}
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="m9 18 6-6-6-6" />
          </svg>
          {labels.showTable}
        </summary>
        <table className="mt-2 w-full text-sm">
          <thead>
            <tr className="text-left">
              <th scope="col">{labels.date}</th>
              <th scope="col">{labels.assessment}</th>
              <th scope="col">{labels.score}</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p, i) => (
              <tr key={`${p.date}-${i}`}>
                <td>{formatDate(p.date)}</td>
                <td>{p.name}</td>
                <td>
                  {p.percent}%{p.grade ? ` (${p.grade})` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

export interface HeatmapUnit {
  id: string;
  name: string;
  topics: ReadonlyArray<{ id: string; name: string; level: MasteryLevel; lessons: number }>;
}

const LEVEL_STYLE: Record<MasteryLevel, string> = {
  not_started: "bg-muted text-foreground",
  learning: "bg-link/15 text-foreground",
  secure: "bg-link/40 text-foreground",
  mastered: "bg-link text-background",
};

/** Topic coverage heatmap: one hue from light (not started) to full (mastered); every
 * cell also names its level and lesson count, so colour is never the only cue. */
export function MasteryHeatmap({
  units,
  levelLabels,
  lessonsLabel,
  legendLabel,
}: {
  units: ReadonlyArray<HeatmapUnit>;
  levelLabels: Record<MasteryLevel, string>;
  lessonsLabel: (count: number) => string;
  legendLabel: string;
}) {
  return (
    <div className="space-y-3">
      <ul aria-label={legendLabel} className="flex flex-wrap gap-2 text-xs">
        {MASTERY_LEVELS.map((level) => (
          <li key={level} className={cn("rounded px-2 py-1", LEVEL_STYLE[level])}>
            {levelLabels[level]}
          </li>
        ))}
      </ul>
      {units.map((unit) => (
        <section key={unit.id} aria-label={unit.name}>
          <h4 className="mb-1 text-sm font-medium">{unit.name}</h4>
          <ul className="grid grid-cols-2 gap-[2px] sm:grid-cols-3 lg:grid-cols-4">
            {unit.topics.map((topic) => (
              <li
                key={topic.id}
                className={cn("rounded px-2 py-1 text-xs", LEVEL_STYLE[topic.level])}
              >
                <span className="block font-medium">{topic.name}</span>
                <span className="block">
                  {levelLabels[topic.level]} · {lessonsLabel(topic.lessons)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
