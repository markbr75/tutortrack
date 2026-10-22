import type { ReactNode } from "react";

import { cn } from "./cn";

/**
 * A `<details>` section for secondary content ("Show as a table", dataset schemas): the
 * summary in link ink at 500 with a 14px chevron that turns a quarter when open, never the
 * browser's marker. `ruled` sets it off above and below with faint row rules when it stands
 * alone; inside a panel it takes the panel's 14×20 row inset (`inPanel`).
 */
export function Disclosure({
  summary,
  children,
  ruled = false,
  inPanel = false,
  className,
  bodyClassName,
}: {
  summary: ReactNode;
  children: ReactNode;
  ruled?: boolean;
  inPanel?: boolean;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <details
      className={cn(
        "group",
        ruled && "border-y border-rule py-3",
        inPanel && "border-t border-border px-5 py-3.5",
        className,
      )}
    >
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1.5 text-sm font-medium text-link [&::-webkit-details-marker]:hidden">
        <svg
          viewBox="0 0 24 24"
          aria-hidden="true"
          className="size-3.5 shrink-0 transition-transform duration-150 group-open:rotate-90"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m9 18 6-6-6-6" />
        </svg>
        {summary}
      </summary>
      <div className={cn("mt-3", bodyClassName)}>{children}</div>
    </details>
  );
}
