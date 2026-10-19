import { cn } from "./cn";

import type { RegisterMarkKind } from "./registerMarks";

const TONE: Record<RegisterMarkKind, string> = {
  completed: "text-foreground",
  missed: "text-margin",
  cancelled: "text-muted-foreground",
  due: "text-margin",
  upcoming: "text-field",
};

export function RegisterMark({
  kind,
  label,
  className,
}: {
  kind: RegisterMarkKind;
  /** What the mark means, read by screen readers ("Completed", "Not marked yet", …). */
  label: string;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 20 20"
      role="img"
      aria-label={label}
      className={cn("size-5 shrink-0", TONE[kind], className)}
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {kind === "completed" ? <path d="M4.5 10.5 8.2 14 15.5 6" strokeWidth={2.2} /> : null}
      {kind === "missed" ? <circle cx="10" cy="10" r="6.5" strokeWidth={2} /> : null}
      {kind === "cancelled" ? (
        <>
          <circle cx="10" cy="10" r="6.5" strokeWidth={1.5} />
          <path d="M5.5 14.5 14.5 5.5" strokeWidth={1.5} />
        </>
      ) : null}
      {kind === "due" || kind === "upcoming" ? (
        <circle cx="10" cy="10" r="6.5" strokeWidth={1.75} strokeDasharray="3 2.6" />
      ) : null}
    </svg>
  );
}
