import { useEffect, useId, useRef, type ReactNode } from "react";

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
  // On narrow screens the row scrolls sideways: keep the selected tab in view (a page can
  // open on a later tab, e.g. ?tab=site) without moving the page itself.
  useEffect(() => {
    const tab = refs.current[value];
    const row = tab?.parentElement;
    if (!tab || !row || row.scrollWidth <= row.clientWidth) return;
    const r = row.getBoundingClientRect();
    const b = tab.getBoundingClientRect();
    if (b.left < r.left || b.right > r.right - 24) row.scrollLeft += b.left - r.left - 16;
  }, [value]);
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
      <div
        role="tablist"
        aria-label={label}
        className="mb-5 flex gap-1 overflow-x-auto border-b border-border pr-6 [mask-image:linear-gradient(to_right,black_calc(100%-1.5rem),transparent)] [scrollbar-width:none]"
      >
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
              "-mb-px shrink-0 border-b-2 border-transparent px-3 py-2 text-sm whitespace-nowrap",
              "text-muted-foreground hover:text-foreground",
              "aria-selected:border-foreground aria-selected:font-semibold aria-selected:text-foreground",
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
