import { useId, type FormEvent, type ReactNode } from "react";

import { Button } from "./Button";
import { cn } from "./cn";
import { PanelFooter, RuledPanel } from "./RuledPanel";

const grids = {
  1: "",
  2: "sm:grid-cols-2",
  3: "sm:grid-cols-2 lg:grid-cols-3",
  4: "sm:grid-cols-2 lg:grid-cols-4",
} as const;

/**
 * A settings-style form in a ruled panel: the title (inside the form, which it names), the
 * fields in a grid, any error, and a ruled footer row with the primary action. `lead` holds
 * secondary actions before it; `trail` quiet ones after it (a ghost Cancel).
 */
export function FormPanel({
  title,
  description,
  submit,
  pending = false,
  disabled = false,
  onSubmit,
  error,
  lead,
  trail,
  columns = 2,
  level,
  className,
  children,
}: {
  title: string;
  description?: ReactNode;
  submit: string;
  pending?: boolean;
  disabled?: boolean;
  onSubmit: () => void;
  /** An alert under the fields. */
  error?: ReactNode;
  lead?: ReactNode;
  trail?: ReactNode;
  columns?: 1 | 2 | 3 | 4;
  level?: 2 | 3;
  className?: string;
  children: ReactNode;
}) {
  const titleId = useId();
  return (
    <form
      aria-labelledby={titleId}
      className={cn("min-w-0", className)}
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <RuledPanel title={title} titleId={titleId} description={description} level={level} flush>
        <div className={cn("grid items-start gap-x-4 gap-y-3 px-5 py-4", grids[columns])}>
          {children}
        </div>
        {error ? <div className="px-5 pb-4">{error}</div> : null}
        <PanelFooter>
          {lead}
          <Button type="submit" loading={pending} disabled={disabled}>
            {submit}
          </Button>
          {trail}
        </PanelFooter>
      </RuledPanel>
    </form>
  );
}
