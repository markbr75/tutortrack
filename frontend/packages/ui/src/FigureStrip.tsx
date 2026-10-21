import type { CSSProperties, ReactNode } from "react";

import { cn } from "./cn";

export interface StripFigure {
  key: string;
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
 * by faint vertical rules (horizontal rules when stacked on phones), each a faded-ink label,
 * the figure at 20px/600 tabular and an optional sentence beneath.
 */
export function FigureStrip({
  figures,
  label,
  className,
}: {
  figures: StripFigure[];
  /** Names the strip for screen readers. */
  label?: string;
  className?: string;
}) {
  return (
    <dl
      aria-label={label}
      style={{ "--tt-strip-cols": Math.max(figures.length, 1) } as CSSProperties}
      className={cn(
        "grid border-y border-border md:[grid-template-columns:repeat(var(--tt-strip-cols),minmax(0,1fr))]",
        className,
      )}
    >
      {figures.map((f) => (
        <div
          key={f.key}
          className="min-w-0 py-4 max-md:border-t max-md:border-rule max-md:first:border-0 md:border-l md:border-rule md:px-5 md:first:border-0 md:first:pl-0"
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
