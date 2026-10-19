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
      {loading && <Spinner />}
      {children}
    </button>
  );
});

/**
 * A thin 16px ring in the current colour. With a label it is a page or section loader: faded
 * ink, and it fades in only after 300ms so quick loads never flash. Without a label it is the
 * immediate inline indicator (buttons, rows), with "Loading" for screen readers.
 */
export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span
      role="status"
      className={cn(
        "inline-flex items-center gap-2",
        label && "animate-appear text-sm text-muted-foreground",
        className,
      )}
    >
      <svg
        className="size-4 shrink-0 animate-spin"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <circle
          cx="12"
          cy="12"
          r="9"
          stroke="currentColor"
          strokeOpacity="0.2"
          strokeWidth="2.25"
        />
        <path
          d="M12 3a9 9 0 0 1 9 9"
          stroke="currentColor"
          strokeWidth="2.25"
          strokeLinecap="round"
        />
      </svg>
      {label ? <span>{label}</span> : <span className="sr-only">Loading</span>}
    </span>
  );
}
