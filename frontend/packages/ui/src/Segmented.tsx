import { cn } from "./cn";

/**
 * A segmented switch between views (list or board, map or list): a clean-leaf strip with an
 * 8px corner and a 1px rule; options in faded ink, the pressed one an ink fill with stock
 * lettering (`aria-pressed`). On phones it can take the full width (`fill`).
 */
export function Segmented<K extends string>({
  label,
  options,
  value,
  onChange,
  fill = false,
  className,
}: {
  label: string;
  options: ReadonlyArray<{ key: K; label: string }>;
  value: K;
  onChange: (key: K) => void;
  /** Share the full width on phones. */
  fill?: boolean;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        "flex rounded-md border border-border bg-surface p-0.5",
        fill && "w-full sm:w-auto",
        className,
      )}
    >
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          aria-pressed={value === option.key}
          onClick={() => onChange(option.key)}
          className={cn(
            "h-7 rounded px-3 text-sm text-muted-foreground hover:text-foreground",
            "aria-pressed:bg-foreground aria-pressed:font-medium aria-pressed:text-background",
            fill && "flex-1 sm:flex-none",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
