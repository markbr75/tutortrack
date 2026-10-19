import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "./cn";

import { buttonClass, type ButtonSize, type ButtonVariant } from "./buttonStyles";

export type { ButtonSize, ButtonVariant };

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading = false, disabled, className, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        buttonClass({ variant, size }),
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {loading && <Spinner className="size-4" />}
      {children}
    </button>
  );
});

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span role="status" className={cn("inline-flex items-center gap-2", className)}>
      <svg className="size-full animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
        <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="4" />
      </svg>
      {label ? <span>{label}</span> : <span className="sr-only">Loading</span>}
    </span>
  );
}
