import type { ReactNode } from "react";

import { cn } from "./cn";

export interface Figure {
  label: ReactNode;
  value: ReactNode;
  /** One sentence of comparison or status, in words. */
  note?: ReactNode;
}

/**
 * Figures as one ruled line, not tiles (the money strip's form): a register rule above and
 * below, each figure a faded-ink label over its value in the figure style, divided by faint
 * vertical rules. On phones an even number of figures sits in a ruled 2-column grid; three
 * stack with faint horizontal rules.
 */
export function FigureStrip({
  figures,
  label,
  className,
}: {
  figures: ReadonlyArray<Figure>;
  /** Accessible name for the strip. */
  label?: string;
  className?: string;
}) {
  const count = Math.min(Math.max(figures.length, 2), 4) as 2 | 3 | 4;
  const columns = { 2: "md:grid-cols-2", 3: "md:grid-cols-3", 4: "md:grid-cols-4" } as const;
  const pairs = figures.length % 2 === 0;
  return (
    <dl
      aria-label={label}
      className={cn(
        "grid border-y border-border",
        pairs && "grid-cols-2",
        columns[count],
        className,
      )}
    >
      {figures.map((figure, index) => (
        <div
          key={index}
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
          <dt className="text-sm text-muted-foreground">{figure.label}</dt>
          <dd className="mt-1 text-xl font-semibold tabular-nums">{figure.value}</dd>
          {figure.note ? <dd className="text-sm text-muted-foreground">{figure.note}</dd> : null}
        </div>
      ))}
    </dl>
  );
}
