import type { ReactNode } from "react";

import { cn } from "./cn";

export interface RuledTableColumn {
  /** Stable React key; falls back to the label. */
  key?: string;
  label: ReactNode;
  /** Figure columns are right-aligned (headings too). */
  align?: "left" | "right";
  /** Keep the heading for screen readers only (an actions column). */
  srOnly?: boolean;
  className?: string;
}

/**
 * A hand-built register table: a positioned, labelled, focusable scroll region (so wide
 * tables scroll inside it and never widen a phone page), a visually hidden caption, headings
 * as 12px/600 faded ink ruled off by a register rule, 10×16 cells with the first and last
 * column inset 20px to line up with a panel's header, and faint rules between rows (global).
 * Standing alone it is a clean-leaf panel with 12px corners; `bare` drops the edge for use
 * inside a flush `RuledPanel`. Rows are passed as `<tr>` children.
 */
export function RuledTable({
  caption,
  columns,
  children,
  empty,
  bare = false,
  className,
}: {
  caption: string;
  columns: ReadonlyArray<RuledTableColumn>;
  children?: ReactNode;
  /** One faded-ink sentence shown instead of the table when there are no rows. */
  empty?: ReactNode;
  bare?: boolean;
  className?: string;
}) {
  return (
    <div
      role="region"
      aria-label={caption}
      tabIndex={0}
      className={cn(
        "relative overflow-x-auto",
        !bare && "rounded-xl border border-border bg-surface",
        className,
      )}
    >
      {empty ? (
        <p className="px-5 py-6 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <table
          className={cn(
            "w-full text-sm",
            "[&_td]:px-4 [&_td]:py-2.5 [&_td]:align-top [&_tbody_th]:px-4 [&_tbody_th]:py-2.5 [&_tbody_th]:text-left [&_tbody_th]:align-top [&_tbody_th]:font-medium",
            "[&_td:first-child]:pl-5 [&_td:last-child]:pr-5 [&_th:first-child]:pl-5 [&_th:last-child]:pr-5",
          )}
        >
          <caption className="sr-only">{caption}</caption>
          <thead className="border-b border-border">
            <tr>
              {columns.map((c, i) => (
                <th
                  key={c.key ?? (typeof c.label === "string" ? c.label : i)}
                  scope="col"
                  className={cn(
                    "px-4 py-2.5 whitespace-nowrap",
                    c.align === "right" && "text-right",
                    c.className,
                  )}
                >
                  {c.srOnly ? <span className="sr-only">{c.label}</span> : c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{children}</tbody>
        </table>
      )}
    </div>
  );
}
