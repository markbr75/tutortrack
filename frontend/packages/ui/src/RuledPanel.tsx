import { useId, type ReactNode } from "react";

import { cn } from "./cn";

export interface RuledPanelProps {
  /** The panel heading (16px/600). Without one the panel is a plain ruled leaf. */
  title?: ReactNode;
  /** Optional id for the heading, when something else points at it. */
  titleId?: string;
  /** Heading level inside the page outline. */
  level?: 2 | 3;
  /** One line of help under the title, in faded ink. */
  description?: ReactNode;
  /** A count, total or status on the right of the header. */
  aside?: ReactNode;
  /** The header rule: the register rule, or margin red for something that still waits. */
  rule?: "border" | "margin";
  /** Leave the body unpadded, for lists, tables and forms that bring their own rows. */
  flush?: boolean;
  /** A ruled footer row: the one link onward, or the panel's Save. */
  footer?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children?: ReactNode;
}

/**
 * A clean-leaf panel on the stock: 12px corners, a register-rule edge, a 14×20 header with
 * the title left and a count or total right, and a ruled footer row. Flat, never raised.
 */
export function RuledPanel({
  title,
  titleId,
  level = 2,
  description,
  aside,
  rule = "border",
  flush = false,
  footer,
  className,
  bodyClassName,
  children,
}: RuledPanelProps) {
  const autoId = useId();
  const id = titleId ?? autoId;
  const Heading = level === 3 ? "h3" : "h2";
  return (
    <section
      aria-labelledby={title ? id : undefined}
      className={cn("min-w-0 rounded-xl border border-border bg-surface", className)}
    >
      {title ? (
        <div
          className={cn(
            "flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b px-5 py-3.5",
            rule === "margin" ? "border-margin" : "border-border",
          )}
        >
          <div className="min-w-0">
            <Heading id={id} className="text-base font-semibold">
              {title}
            </Heading>
            {description ? (
              <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
            ) : null}
          </div>
          {aside ? <div className="text-sm">{aside}</div> : null}
        </div>
      ) : null}
      {flush ? children : <div className={cn("px-5 py-4", bodyClassName)}>{children}</div>}
      {footer ? <PanelFooter>{footer}</PanelFooter> : null}
    </section>
  );
}

/** The ruled footer row of a panel (or of a form inside a flush panel). */
export function PanelFooter({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 border-t border-rule px-5 py-3 text-sm",
        className,
      )}
    >
      {children}
    </div>
  );
}
