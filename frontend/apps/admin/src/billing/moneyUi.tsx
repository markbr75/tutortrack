import { useTranslation } from "@tutortrack/i18n";
import { cn } from "@tutortrack/ui";
import { useSyncExternalStore, type ReactNode } from "react";

/** An invoice's state in words: overdue in margin red, everything else in ink or faded ink. */
export function InvoiceStatus({
  status,
  overdue,
  className,
}: {
  status: string;
  overdue?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();
  return (
    <span
      className={cn(
        overdue
          ? "font-semibold text-margin"
          : status === "draft" || status === "void" || status === "written_off"
            ? "text-muted-foreground"
            : "",
        className,
      )}
    >
      {overdue ? t("billing.status.overdue") : t(`billing.status.${status}`)}
    </span>
  );
}

/** A right-aligned column heading for figures. */
export function EndHead({ children }: { children: ReactNode }) {
  return <span className="block text-right">{children}</span>;
}

/** A right-aligned, tabular figure in a table cell. */
export function Figure({ children, strong }: { children: ReactNode; strong?: boolean }) {
  return (
    <span className={cn("block text-right tabular-nums", strong && "font-semibold")}>
      {children}
    </span>
  );
}

/** A row in a ruled list panel: faint rule between rows, 10×20 padding. */
export const rowClass = "border-t border-rule px-5 py-2.5 first:border-0";

/** Shared look for the empty sentence inside a panel. */
export function PanelEmpty({ children }: { children: ReactNode }) {
  return <p className="px-5 py-6 text-sm text-muted-foreground">{children}</p>;
}

/** Skeleton rows while a panel's list loads, announced once. */
export function PanelLoading({ label }: { label: string }) {
  return (
    <div className="space-y-3 px-5 py-4">
      <span role="status" className="sr-only">
        {label}
      </span>
      <div aria-hidden="true" className="h-4 animate-pulse rounded bg-muted" />
      <div aria-hidden="true" className="h-4 animate-pulse rounded bg-muted" />
    </div>
  );
}

const PHONE = "(max-width: 767px)";

function subscribe(onChange: () => void) {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const query = window.matchMedia(PHONE);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** True below 768px, where money tables fold secondary columns into context lines. */
export function useIsPhone(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(PHONE).matches : false),
    () => false,
  );
}
