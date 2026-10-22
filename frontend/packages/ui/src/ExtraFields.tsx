import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";

import { cn } from "./cn";

function Message({ id, hint, error }: { id: string; hint?: string; error?: string }) {
  if (error)
    return (
      <p id={`${id}-error`} className="text-xs text-danger" role="alert">
        {error}
      </p>
    );
  if (hint)
    return (
      <p id={`${id}-hint`} className="text-xs text-muted-foreground">
        {hint}
      </p>
    );
  return null;
}

const described = (id: string, hint?: string, error?: string) =>
  error ? `${id}-error` : hint ? `${id}-hint` : undefined;

export interface TextAreaFieldProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  hideLabel?: boolean;
  hint?: string;
  error?: string;
}

/** A labelled textarea: the shared field look (field edge, 8px corners), hint or error below. */
export const TextAreaField = forwardRef<HTMLTextAreaElement, TextAreaFieldProps>(
  function TextAreaField(
    { label, hideLabel, hint, error, id, className, rows = 3, ...props },
    ref,
  ) {
    const autoId = useId();
    const fieldId = id ?? autoId;
    return (
      <div className="flex flex-col gap-1">
        <label htmlFor={fieldId} className={hideLabel ? "sr-only" : "text-sm font-medium"}>
          {label}
        </label>
        <textarea
          ref={ref}
          id={fieldId}
          rows={rows}
          aria-invalid={error ? true : undefined}
          aria-describedby={described(fieldId, hint, error)}
          className={cn(
            "w-full rounded-md border border-field bg-surface px-3 py-2 text-sm aria-[invalid=true]:border-danger",
            className,
          )}
          {...props}
        />
        <Message id={fieldId} hint={hint} error={error} />
      </div>
    );
  },
);

export interface CheckboxFieldProps extends Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "type" | "children"
> {
  label: ReactNode;
  hint?: string;
}

/** A checkbox with its label beside it (16px box, body text) and an optional caption hint. */
export const CheckboxField = forwardRef<HTMLInputElement, CheckboxFieldProps>(
  function CheckboxField({ label, hint, id, className, ...props }, ref) {
    const autoId = useId();
    const fieldId = id ?? autoId;
    return (
      <div className={cn("flex flex-col gap-0.5", className)}>
        <label htmlFor={fieldId} className="flex items-start gap-2 text-sm">
          <input
            ref={ref}
            id={fieldId}
            type="checkbox"
            className="mt-0.5 size-4 shrink-0"
            aria-describedby={hint ? `${fieldId}-hint` : undefined}
            {...props}
          />
          <span>{label}</span>
        </label>
        {hint ? (
          <p id={`${fieldId}-hint`} className="pl-6 text-xs text-muted-foreground">
            {hint}
          </p>
        ) : null}
      </div>
    );
  },
);

export interface UnitFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  label: string;
  hideLabel?: boolean;
  /** The unit after the field, in faded ink ("days", "%"). */
  unit?: string;
  hint?: string;
  error?: string;
  /** "sm" (36px) for compact rows. */
  size?: "md" | "sm";
}

/**
 * A short numeric setting: a 96px right-aligned tabular field followed by its unit in faded
 * ink, with the label above and a hint or error below.
 */
export const UnitField = forwardRef<HTMLInputElement, UnitFieldProps>(function UnitField(
  { label, hideLabel, unit, hint, error, id, className, size = "md", type = "number", ...props },
  ref,
) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={fieldId} className={hideLabel ? "sr-only" : "text-sm font-medium"}>
        {label}
      </label>
      <div className="flex items-center gap-2">
        <input
          ref={ref}
          id={fieldId}
          type={type}
          inputMode="numeric"
          aria-invalid={error ? true : undefined}
          aria-describedby={described(fieldId, hint, error)}
          className={cn(
            "w-24 rounded-md border border-field bg-surface px-3 text-right text-sm tabular-nums aria-[invalid=true]:border-danger",
            size === "sm" ? "h-9" : "h-10",
            className,
          )}
          {...props}
        />
        {unit ? <span className="text-sm text-muted-foreground">{unit}</span> : null}
      </div>
      <Message id={fieldId} hint={hint} error={error} />
    </div>
  );
});
