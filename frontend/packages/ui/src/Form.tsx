import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";

import { cn } from "./cn";

const control =
  "w-full rounded-md border border-field bg-surface px-3 text-sm aria-[invalid=true]:border-danger";
const heights = { md: "h-10", sm: "h-9" } as const;

interface FieldShellProps {
  id: string;
  label: string;
  /** Keep the label for screen readers only, where the control speaks for itself. */
  hideLabel?: boolean;
  hint?: string;
  error?: string;
  children: ReactNode;
}

function FieldShell({ id, label, hideLabel, hint, error, children }: FieldShellProps) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className={hideLabel ? "sr-only" : "text-sm font-medium"}>
        {label}
      </label>
      {children}
      {hint && !error ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function describedBy(id: string, hint?: string, error?: string): string | undefined {
  if (error) return `${id}-error`;
  if (hint) return `${id}-hint`;
  return undefined;
}

export interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  label: string;
  hideLabel?: boolean;
  /** "sm" for compact filter bars. */
  size?: "md" | "sm";
  hint?: string;
  error?: string;
}

/** Labelled input with hint and error text wired up for screen readers (WCAG 2.2 AA). */
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, hideLabel, size = "md", hint, error, id, className, ...props },
  ref,
) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldShell id={fieldId} label={label} hideLabel={hideLabel} hint={hint} error={error}>
      <input
        ref={ref}
        id={fieldId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fieldId, hint, error)}
        className={cn(control, heights[size], className)}
        {...props}
      />
    </FieldShell>
  );
});

export interface SelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  label: string;
  hideLabel?: boolean;
  /** "sm" for compact filter bars. */
  size?: "md" | "sm";
  hint?: string;
  error?: string;
  options: ReadonlyArray<{ value: string; label: string }>;
}

export const SelectField = forwardRef<HTMLSelectElement, SelectFieldProps>(function SelectField(
  { label, hideLabel, size = "md", hint, error, id, options, className, ...props },
  ref,
) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldShell id={fieldId} label={label} hideLabel={hideLabel} hint={hint} error={error}>
      <select
        ref={ref}
        id={fieldId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fieldId, hint, error)}
        className={cn(control, heights[size], className)}
        {...props}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </FieldShell>
  );
});

export interface AlertProps {
  tone?: "info" | "warning" | "danger" | "success";
  title?: string;
  children?: ReactNode;
  className?: string;
}

const tones = {
  info: "border-border bg-surface",
  warning: "border-warning/40 bg-warning/10",
  danger: "border-danger/40 bg-danger/10",
  success: "border-success/40 bg-success/10",
};

export function Alert({ tone = "info", title, children, className }: AlertProps) {
  return (
    <div
      role={tone === "danger" || tone === "warning" ? "alert" : "status"}
      className={cn("rounded-md border px-4 py-3 text-sm", tones[tone], className)}
    >
      {title ? <p className="font-medium">{title}</p> : null}
      {children}
    </div>
  );
}
