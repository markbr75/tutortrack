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
 * vertical rules (horizontal rules when stacked on phones).
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
  const columns = { 2: "md:grid-cols-2", 3: "md:grid-cols-3", 4: "md:grid-cols-4" } as const;
  return (
    <dl
      aria-label={label}
      className={cn(
        "grid border-y border-border",
        columns[Math.min(Math.max(figures.length, 2), 4) as 2 | 3 | 4],
        className,
      )}
    >
      {figures.map((figure, index) => (
        <div
          key={index}
          className="min-w-0 py-4 max-md:border-t max-md:border-rule max-md:first:border-0 md:border-l md:border-rule md:px-5 md:first:border-0 md:first:pl-0"
        >
          <dt className="text-sm text-muted-foreground">{figure.label}</dt>
          <dd className="mt-1 text-xl font-semibold tabular-nums">{figure.value}</dd>
          {figure.note ? <dd className="text-sm text-muted-foreground">{figure.note}</dd> : null}
        </div>
      ))}
    </dl>
  );
}
