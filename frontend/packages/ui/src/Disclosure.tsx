import type { ReactNode } from "react";

import { cn } from "./cn";

/**
 * A `<details>` section for secondary content: the summary in link ink at 500 with a 14px
 * chevron (no native marker) that turns 90° in 150ms when open.
 */
export function Disclosure({
  summary,
  children,
  open,
  className,
  summaryClassName,
}: {
  summary: ReactNode;
  children: ReactNode;
  open?: boolean;
  className?: string;
  summaryClassName?: string;
}) {
  return (
    <details className={cn("group", className)} open={open}>
      <summary
        className={cn(
          "flex w-fit cursor-pointer list-none items-center gap-1.5 text-sm font-medium text-link [&::-webkit-details-marker]:hidden",
          summaryClassName,
        )}
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="size-3.5 shrink-0 transition-transform duration-150 group-open:rotate-90 motion-reduce:transition-none"
        >
          <path d="m9 18 6-6-6-6" />
        </svg>
        {summary}
      </summary>
      {children}
    </details>
  );
}
