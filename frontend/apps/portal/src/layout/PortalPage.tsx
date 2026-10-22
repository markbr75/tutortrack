import { useTranslation } from "@tutortrack/i18n";
import { cn } from "@tutortrack/ui";
import { ChevronLeft } from "lucide-react";
import {
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";

/**
 * A portal screen's header: an optional way back (faded ink, a 16px chevron), the title at
 * 20px/600 (the portal titles one step below the admin's headline), one line of context in
 * faded ink, and the actions on the right, wrapping under the title on phones (primary last).
 * The way back is a line of links, not a navigation landmark: the portal shows one at a time.
 */
export function PortalHeader({
  title,
  description,
  actions,
  back,
  titleId,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  back?: ReactNode;
  titleId?: string;
  className?: string;
}) {
  return (
    <header className={cn("mb-6", className)}>
      {back ? (
        <p className="mb-1.5 flex flex-wrap items-center gap-x-1.5 text-sm text-muted-foreground [&_a]:underline-offset-2 [&_a]:hover:text-foreground [&_a]:hover:underline">
          <ChevronLeft aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.75} />
          {back}
        </p>
      ) : null}
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 id={titleId} className="text-xl font-semibold text-balance">
            {title}
          </h1>
          {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}

/** A margin-red count pill for waiting items; hidden from assistive tech (say it in words). */
export function CountPill({ count, className }: { count: number; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-margin px-1.5 text-xs leading-4 font-semibold text-margin-foreground tabular-nums",
        className,
      )}
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}

/** The one faded-ink sentence inside an empty panel. */
export function PanelEmpty({ children }: { children: ReactNode }) {
  return <p className="px-5 py-6 text-sm text-muted-foreground">{children}</p>;
}

/** Two pulsing wash bars while a panel's list loads, announced once. */
export function PanelLoading({ label }: { label: string }) {
  return (
    <div className="space-y-3 px-5 py-4">
      <span role="status" className="sr-only">
        {label}
      </span>
      <div aria-hidden="true" className="h-4 w-2/3 animate-pulse rounded bg-muted" />
      <div aria-hidden="true" className="h-4 w-1/2 animate-pulse rounded bg-muted" />
    </div>
  );
}

/** A status in words: margin red at 600 for what waits or is overdue, faded ink for closed. */
export function Word({
  tone = "ink",
  children,
  className,
}: {
  tone?: "ink" | "margin" | "muted" | "danger";
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        tone === "margin" && "font-semibold text-margin",
        tone === "muted" && "text-muted-foreground",
        tone === "danger" && "font-medium text-danger",
        className,
      )}
    >
      {children}
    </span>
  );
}

const fieldEdge =
  "w-full rounded-md border border-field bg-surface px-3 py-2 text-sm aria-[invalid=true]:border-danger disabled:opacity-60";

/** A labelled textarea with its hint and error, in the shared field style. */
export function TextAreaField({
  label,
  hint,
  error,
  className,
  labelAside,
  id,
  ...props
}: Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "children"> & {
  label: string;
  hint?: string;
  error?: string;
  /** Something beside the label (a dictation button). */
  labelAside?: ReactNode;
}) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  const describedBy = error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor={fieldId} className="text-sm font-medium">
          {label}
        </label>
        {labelAside}
      </div>
      <textarea
        id={fieldId}
        rows={3}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={fieldEdge}
        {...props}
      />
      {hint && !error ? (
        <p id={`${fieldId}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${fieldId}-error`} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** A labelled file input whose button takes the secondary button's look. */
export function FileField({
  label,
  hint,
  className,
  id,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label: string; hint?: string }) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <label htmlFor={fieldId} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={fieldId}
        type="file"
        aria-describedby={hint ? `${fieldId}-hint` : undefined}
        className="max-w-full text-sm text-muted-foreground file:mr-3 file:h-9 file:cursor-pointer file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:text-sm file:font-medium file:text-foreground hover:file:bg-muted"
        {...props}
      />
      {hint ? (
        <p id={`${fieldId}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/** A checkbox with its label to the right, at body size. */
export function CheckField({
  label,
  className,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label: ReactNode }) {
  return (
    <label className={cn("flex items-start gap-2 text-sm", className)}>
      <input type="checkbox" className="mt-0.5 size-4 shrink-0" {...props} />
      <span>{label}</span>
    </label>
  );
}

/** The "Saved." note beside a panel's Save, in success. */
export function SavedNote({ show }: { show: boolean }) {
  const { t } = useTranslation();
  return (
    <span role="status" className="text-sm text-success">
      {show ? t("portal.saved") : ""}
    </span>
  );
}
