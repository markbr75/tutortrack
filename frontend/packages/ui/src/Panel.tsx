import { useId, type ReactNode } from "react";

import { cn } from "./cn";

/**
 * A ruled panel: a clean leaf on the stock with a register-rule edge and 12px corners. The
 * header (14px × 20px) holds the title left and a count, total or action right, ruled off
 * below; the body is inset 20px, or `flush` for ruled rows and tables that set their own
 * padding; an optional footer row holds the one link onward.
 */
export function Panel({
  title,
  aside,
  footer,
  flush = false,
  rule,
  label,
  className,
  bodyClassName,
  children,
}: {
  /** The panel's heading (an h2). Without it the panel is a plain ruled leaf. */
  title?: ReactNode;
  /** Right side of the header: a count, total or one small action. */
  aside?: ReactNode;
  /** A ruled footer row (the link onward). */
  footer?: ReactNode;
  /** Leave the body unpadded (ruled rows, tables). */
  flush?: boolean;
  /** The header's rule colour class; `border-margin` only while something waits. */
  rule?: string;
  /** Accessible name when the panel has no visible title. */
  label?: string;
  className?: string;
  bodyClassName?: string;
  children?: ReactNode;
}) {
  const id = useId();
  return (
    <section
      aria-labelledby={title ? id : undefined}
      aria-label={title ? undefined : label}
      className={cn("min-w-0 rounded-xl border border-border bg-surface", className)}
    >
      {title ? (
        <div
          className={cn(
            "flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b px-5 py-3.5",
            rule ?? "border-border",
          )}
        >
          <h2 id={id} className="text-base font-semibold">
            {title}
          </h2>
          {aside ? <div className="flex items-center gap-2 text-sm">{aside}</div> : null}
        </div>
      ) : null}
      <div className={cn(flush ? undefined : "px-5 py-4", bodyClassName)}>{children}</div>
      {footer ? <div className="border-t border-rule px-5 py-3 text-sm">{footer}</div> : null}
    </section>
  );
}

/** Ruled list rows inside a flush panel: 10px × 20px, faint rules between rows. */
export function PanelRows({ children, className }: { children: ReactNode; className?: string }) {
  return <ul className={cn("divide-y divide-rule", className)}>{children}</ul>;
}

/** One ruled row (use inside `PanelRows`). */
export function PanelRow({ children, className }: { children: ReactNode; className?: string }) {
  return <li className={cn("px-5 py-2.5 text-sm", className)}>{children}</li>;
}

/**
 * Label and value pairs as ruled rows (label in faded ink, value in ink). Empty values are
 * left out unless `empty` names what to show instead.
 */
export function FactList({
  items,
  empty,
  none,
  className,
}: {
  items: ReadonlyArray<readonly [string, ReactNode]>;
  /** Shown for an empty value; without it the row is left out. */
  empty?: string;
  /** One faded-ink sentence when there is nothing to list. */
  none?: string;
  className?: string;
}) {
  const shown = items
    .map(([label, value]) => {
      const blank = value === null || value === undefined || value === "";
      return [label, blank ? (empty ?? null) : value] as const;
    })
    .filter(([, value]) => value !== null);
  if (!shown.length) {
    return none ? <p className="px-5 py-4 text-sm text-muted-foreground">{none}</p> : null;
  }
  return (
    <dl className={cn("divide-y divide-rule text-sm", className)}>
      {shown.map(([label, value]) => (
        <div
          key={label}
          className="grid grid-cols-[minmax(6rem,40%)_minmax(0,1fr)] gap-x-4 px-5 py-2.5"
        >
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * One name plate per person: the name, then one line of context in faded ink. Pass a link as
 * `name` to make the name the way to the record.
 */
export function NamePlate({
  name,
  context,
  aside,
  className,
}: {
  name: ReactNode;
  context?: ReactNode;
  /** Right-aligned action or fact (a button, an amount). */
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1", className)}>
      <div className="min-w-0">
        <div className="font-medium">{name}</div>
        {context ? <div className="text-xs text-muted-foreground">{context}</div> : null}
      </div>
      {aside ? <div className="flex shrink-0 flex-wrap items-center gap-2">{aside}</div> : null}
    </div>
  );
}
