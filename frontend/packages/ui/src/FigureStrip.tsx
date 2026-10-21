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
 */
export function FigureStrip({
  figures,
  label,
  className,
}: {
  figures: ReadonlyArray<StripFigure>;
  /** Names the strip for screen readers. */
  label?: string;
  className?: string;
}) {
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
