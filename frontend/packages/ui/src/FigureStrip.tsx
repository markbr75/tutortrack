import type { CSSProperties, ReactNode } from "react";

import { cn } from "./cn";

export interface StripFigure {
  /** Stable React key; falls back to the figure's position. */
  key?: string;
  label: ReactNode;
  value: ReactNode;
  /** One sentence of comparison or status, in words. */
  note?: ReactNode;
  /** Margin red only for overdue or waiting; danger only for errors. */
  tone?: "default" | "margin" | "success" | "danger";
}

const noteTones = {
  default: "text-muted-foreground",
  margin: "font-medium text-margin",
  success: "text-success",
  danger: "font-medium text-danger",
};

/**
 * Figures read as one ruled line, not tiles: a register rule above and below, figures divided
 * by faint vertical rules, each a faded-ink label, the figure at 20px/600 tabular and an
 * optional sentence beneath. On phones an even number of figures sits in a ruled 2-column
 * grid; an odd number stacks with faint horizontal rules.
 *
 * `columns` lays many figures out as one ruled grid instead: that many columns from 768px and
 * two on phones, rows ruled off by faint horizontal rules, so the vertical rules line up from
 * row to row. A short last row is closed by letting its last figure span the rest of it.
 */
export function FigureStrip({
  figures,
  label,
  className,
  columns,
}: {
  figures: ReadonlyArray<StripFigure>;
  /** Names the strip for screen readers. */
  label?: string;
  className?: string;
  /** Wraps the figures into a fixed number of columns from 768px (two on phones). */
  columns?: number;
}) {
  if (columns)
    return <FigureGrid figures={figures} label={label} className={className} columns={columns} />;
  const pairs = figures.length % 2 === 0;
  return (
    <dl
      aria-label={label}
      style={{ "--tt-strip-cols": Math.max(figures.length, 1) } as CSSProperties}
      className={cn(
        "grid border-y border-border md:[grid-template-columns:repeat(var(--tt-strip-cols),minmax(0,1fr))]",
        pairs && "grid-cols-2",
        className,
      )}
    >
      {figures.map((f, index) => (
        <div
          key={f.key ?? index}
          className={cn(
            "min-w-0 py-4 md:border-t-0 md:border-l md:border-rule md:px-5 md:first:border-l-0 md:first:pl-0",
            pairs
              ? cn(
                  index >= 2 && "border-t border-rule",
                  index % 2 === 1 ? "border-l border-rule pl-4" : "pr-4",
                )
              : "border-t border-rule first:border-t-0",
          )}
        >
          <dt className="text-sm text-muted-foreground">{f.label}</dt>
          <dd
            className={cn(
              "mt-1 text-xl font-semibold tabular-nums",
              f.tone === "margin" && !f.note && "text-margin",
              f.tone === "danger" && !f.note && "text-danger",
            )}
          >
            {f.value}
          </dd>
          {f.note ? (
            <dd className={cn("text-sm", noteTones[f.tone ?? "default"])}>{f.note}</dd>
          ) : null}
        </div>
      ))}
    </dl>
  );
}

function FigureValue({ f }: { f: StripFigure }) {
  return (
    <>
      <dt className="text-sm text-muted-foreground">{f.label}</dt>
      <dd
        className={cn(
          "mt-1 text-xl font-semibold tabular-nums",
          f.tone === "margin" && !f.note && "text-margin",
          f.tone === "danger" && !f.note && "text-danger",
        )}
      >
        {f.value}
      </dd>
      {f.note ? <dd className={cn("text-sm", noteTones[f.tone ?? "default"])}>{f.note}</dd> : null}
    </>
  );
}

function FigureGrid({
  figures,
  label,
  className,
  columns,
}: {
  figures: ReadonlyArray<StripFigure>;
  label?: string;
  className?: string;
  columns: number;
}) {
  const count = figures.length;
  // How many columns the last figure takes to close its row (phone: 2, wide: `columns`).
  const span = (cols: number) => (count % cols === 0 ? 1 : cols - (count % cols) + 1);
  return (
    <dl
      aria-label={label}
      style={{ "--tt-strip-cols": columns } as CSSProperties}
      className={cn(
        "grid grid-cols-2 border-y border-border md:[grid-template-columns:repeat(var(--tt-strip-cols),minmax(0,1fr))]",
        className,
      )}
    >
      {figures.map((f, index) => {
        const last = index === count - 1;
        const phoneCol = index % 2;
        const wideCol = index % columns;
        return (
          <div
            key={f.key ?? index}
            style={
              last
                ? ({
                    "--tt-span": span(2),
                    "--tt-span-md": span(columns),
                  } as CSSProperties)
                : undefined
            }
            className={cn(
              "min-w-0 border-rule py-4",
              last &&
                "[grid-column:span_var(--tt-span)/span_var(--tt-span)] md:[grid-column:span_var(--tt-span-md)/span_var(--tt-span-md)]",
              // Phones: two columns.
              index >= 2 && "border-t",
              phoneCol === 1 ? "border-l pl-4" : "pr-4",
              // From 768px: `columns` columns.
              index >= columns ? "md:border-t" : "md:border-t-0",
              wideCol === 0 ? "md:border-l-0 md:pl-0" : "md:border-l md:pl-5",
              "md:pr-5",
            )}
          >
            <FigureValue f={f} />
          </div>
        );
      })}
    </dl>
  );
}
