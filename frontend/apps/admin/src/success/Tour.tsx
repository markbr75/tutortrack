import { useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";

import type { TourDefinition } from "./tours";

// The highlight is link ink, never the tenant colour (the Tenant Fills, the Register Inks Rule).
const HIGHLIGHT = ["outline", "outline-2", "outline-offset-4", "outline-link"];

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export interface TourProps {
  tour: TourDefinition;
  /** `completed` after the last step, `dismissed` on Escape or "Skip tour". */
  onFinish: (outcome: "completed" | "dismissed") => void;
}

/**
 * An accessible product tour (WCAG 2.2 AA): a non-modal dialog that takes focus on each
 * step (its heading), announces "Step n of m", closes on Escape, returns focus to where
 * the person was, outlines the step's element and scrolls it into view without animation
 * when reduced motion is preferred. The page stays usable underneath.
 */
export function Tour({ tour, onFinish }: TourProps) {
  const { t } = useTranslation();
  const [index, setIndex] = useState(0);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const titleId = useId();
  const bodyId = useId();
  const step = tour.steps[index]!;
  const last = index === tour.steps.length - 1;

  useEffect(() => {
    returnFocus.current = document.activeElement as HTMLElement | null;
    return () => returnFocus.current?.focus?.();
  }, []);

  useLayoutEffect(() => {
    const target = step.target ? document.querySelector<HTMLElement>(step.target) : null;
    if (target) {
      target.classList.add(...HIGHLIGHT);
      target.scrollIntoView?.({
        block: "center",
        behavior: prefersReducedMotion() ? "auto" : "smooth",
      });
      const rect = target.getBoundingClientRect();
      const width = Math.min(360, window.innerWidth - 32);
      const below = rect.bottom + 12;
      setPosition({
        top: below + 220 < window.innerHeight ? below : Math.max(16, rect.top - 232),
        left: Math.min(Math.max(16, rect.left), window.innerWidth - width - 16),
      });
    } else {
      setPosition(null);
    }
    headingRef.current?.focus();
    return () => target?.classList.remove(...HIGHLIGHT);
  }, [step]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onFinish("dismissed");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onFinish]);

  const base = `tours.${tour.key}.${step.key}`;
  return (
    <div
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      className="fixed z-50 w-[min(360px,calc(100vw-2rem))] rounded-xl border border-border bg-surface px-5 py-4 text-foreground shadow-[0_8px_24px_-8px_rgb(15_23_42/0.25)] motion-safe:transition-[top,left]"
      style={
        position
          ? { top: position.top, left: position.left }
          : { bottom: 24, left: "50%", transform: "translateX(-50%)" }
      }
    >
      <p className="text-xs text-muted-foreground tabular-nums" aria-live="polite">
        {t("tours.progress", { current: index + 1, total: tour.steps.length })}
      </p>
      <h2
        id={titleId}
        ref={headingRef}
        tabIndex={-1}
        className="mt-1 text-base font-semibold outline-none"
      >
        {t(`${base}.title`)}
      </h2>
      <p id={bodyId} className="mt-2 text-sm">
        {t(`${base}.body`)}
      </p>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <Button
          size="sm"
          variant="ghost"
          className="-ml-3 text-muted-foreground"
          onClick={() => onFinish("dismissed")}
        >
          {t("tours.skip")}
        </Button>
        <div className="flex gap-2">
          {index > 0 ? (
            <Button size="sm" variant="secondary" onClick={() => setIndex((i) => i - 1)}>
              {t("tours.back")}
            </Button>
          ) : null}
          <Button size="sm" onClick={() => (last ? onFinish("completed") : setIndex((i) => i + 1))}>
            {last ? t("tours.done") : t("tours.next")}
          </Button>
        </div>
      </div>
    </div>
  );
}
