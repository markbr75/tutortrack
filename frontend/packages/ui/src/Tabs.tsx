import { useId, useRef, type ReactNode } from "react";

import { cn } from "./cn";

export interface TabItem<K extends string> {
  key: K;
  label: string;
}

export interface TabsProps<K extends string> {
  label: string;
  tabs: ReadonlyArray<TabItem<K>>;
  value: K;
  onChange: (key: K) => void;
  children: ReactNode;
  className?: string;
}

/** WAI-ARIA tabs with roving focus (arrow keys, Home/End). Renders the active panel only. */
export function Tabs<K extends string>({
  label,
  tabs,
  value,
  onChange,
  children,
  className,
}: TabsProps<K>) {
  const baseId = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const move = (from: K, step: number | "first" | "last") => {
    const index = tabs.findIndex((t) => t.key === from);
    const nextIndex =
      step === "first"
        ? 0
        : step === "last"
          ? tabs.length - 1
          : (index + step + tabs.length) % tabs.length;
    const next = tabs[nextIndex];
    if (!next) return;
    onChange(next.key);
    refs.current[next.key]?.focus();
  };
  return (
    <div className={className}>
      <div role="tablist" aria-label={label} className="mb-4 flex flex-wrap gap-1 border-b">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            ref={(el) => {
              refs.current[tab.key] = el;
            }}
            type="button"
            role="tab"
            id={`${baseId}-${tab.key}`}
            aria-selected={value === tab.key}
            aria-controls={`${baseId}-panel`}
            tabIndex={value === tab.key ? 0 : -1}
            className={cn(
              "-mb-px border-b-2 border-transparent px-3 py-2 text-sm",
              "aria-selected:border-primary aria-selected:font-medium",
            )}
            onClick={() => onChange(tab.key)}
            onKeyDown={(e) => {
              const step =
                e.key === "ArrowRight"
                  ? 1
                  : e.key === "ArrowLeft"
                    ? -1
                    : e.key === "Home"
                      ? "first"
                      : e.key === "End"
                        ? "last"
                        : null;
              if (step === null) return;
              e.preventDefault();
              move(tab.key, step);
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${baseId}-panel`} aria-labelledby={`${baseId}-${value}`}>
        {children}
      </div>
    </div>
  );
}
