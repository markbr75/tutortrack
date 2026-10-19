import type { ReactNode } from "react";

import { cn } from "./cn";

/** A page's title, one line of context and its actions (the primary one last, on the right). */
export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn("mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3", className)}
    >
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold">{title}</h1>
        {description ? <p className="mt-1 text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
