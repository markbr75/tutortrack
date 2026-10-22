import type { ReactNode } from "react";

import { cn } from "./cn";

export interface RuledColumn {
  /** Stable key; falls back to the position. */
  key?: string;
  header: ReactNode;
  /** A figure column: right-aligned heading and cells (pair with `figureCell`). */
  end?: boolean;
  /** A centred column (a register mark). */
  center?: boolean;
  /** A fixed width class for figure or mark columns ("w-32" for an amount). */
  width?: string;
  /** Keep the heading for screen readers only (an actions column). */
  hidden?: boolean;
}

/** The class for a right-aligned, tabular figure cell. */
export const figureCell = "text-right tabular-nums whitespace-nowrap";

/**
 * A hand-built register table: a positioned, labelled, focusable scroll region (so wide
 * content scrolls inside it and never widens the page), a visually hidden caption, the header
 * ruled off by a register rule, faint rules between rows and cells inset 10×16 (20 at the
 * panel edges). Inside a flush `RuledPanel` it is bare; on its own (`framed`) it is a
 * clean-leaf panel like the data grid. Rows are plain `<tr>`/`<td>` children.
 */
export function RuledTable({
  caption,
  columns,
  children,
  footer,
  framed = false,
  loading = false,
  loadingLabel,
  empty,
  className,
  tableClassName,
}: {
  caption: string;
  columns: ReadonlyArray<RuledColumn>;
  children?: ReactNode;
  /** A `<tfoot>` with totals, ruled off by a register rule. */
  footer?: ReactNode;
  framed?: boolean;
  loading?: boolean;
  loadingLabel?: string;
  /** One faded-ink sentence instead of rows (pass it only when there are none). */
  empty?: ReactNode;
  className?: string;
  tableClassName?: string;
}) {
  return (
    <div
      role="region"
      aria-label={caption}
      tabIndex={0}
      className={cn(
        "relative overflow-x-auto",
        framed && "rounded-xl border border-border bg-surface",
        className,
      )}
    >
      <table
        className={cn(
          "w-full text-left text-sm",
          // Low-specificity defaults, so a cell's own classes (py-1.5, align-middle) win.
          "[:where(&)_td]:px-4 [:where(&)_td]:py-2.5 [:where(&)_td]:align-top",
          "[:where(&)_td:first-child]:pl-5 [:where(&)_td:last-child]:pr-5",
          "[:where(&)_th]:px-4 [:where(&)_th:first-child]:pl-5 [:where(&)_th:last-child]:pr-5",
          tableClassName,
        )}
      >
        <caption className="sr-only">{caption}</caption>
        <thead className="border-b border-border">
          <tr>
            {columns.map((column, index) => (
              <th
                key={column.key ?? index}
                scope="col"
                className={cn(
                  "py-2.5 whitespace-nowrap",
                  column.end && "text-right",
                  column.center && "text-center",
                  column.width,
                )}
              >
                {column.hidden ? <span className="sr-only">{column.header}</span> : column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            [0, 1, 2].map((i) => (
              <tr key={`loading-${i}`}>
                <td colSpan={columns.length}>
                  {i === 0 && loadingLabel ? (
                    <span role="status" className="sr-only">
                      {loadingLabel}
                    </span>
                  ) : null}
                  <div aria-hidden="true" className="h-4 animate-pulse rounded bg-muted" />
                </td>
              </tr>
            ))
          ) : empty ? (
            <tr>
              <td colSpan={columns.length} className="py-8 text-center text-muted-foreground">
                {empty}
              </td>
            </tr>
          ) : (
            children
          )}
        </tbody>
        {footer && !loading && !empty ? (
          <tfoot className="border-t border-border">{footer}</tfoot>
        ) : null}
      </table>
    </div>
  );
}
