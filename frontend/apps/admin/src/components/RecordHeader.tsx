import { useTranslation } from "@tutortrack/i18n";
import { Button, PageHeader } from "@tutortrack/ui";
import { ChevronLeft } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * A record page's header: the way back (one or more links, faded ink), then the shared page
 * header with the record's name, its one line of context and its actions.
 */
export function RecordHeader({
  back,
  title,
  description,
  actions,
}: {
  back?: ReactNode;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <>
      {back ? (
        <nav
          aria-label={t("designS5.back")}
          className="mb-1.5 flex flex-wrap items-center gap-x-1.5 text-sm text-muted-foreground [&_a]:hover:text-foreground [&_a]:hover:underline"
        >
          <ChevronLeft aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.75} />
          {back}
        </nav>
      ) : null}
      <PageHeader title={title} description={description} actions={actions} />
    </>
  );
}

/** One leading work area with a subordinate 22rem side column (stacked below on phones). */
export function RecordLayout({ main, side }: { main: ReactNode; side?: ReactNode }) {
  if (!side) return <div className="space-y-6">{main}</div>;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="min-w-0 space-y-6">{main}</div>
      <aside className="min-w-0 space-y-6">{side}</aside>
    </div>
  );
}

/** The separator between two back links. */
export function BackSeparator() {
  return <span aria-hidden="true">·</span>;
}

/**
 * A small secondary action in the record header that opens its form in place (status
 * changes): the button gives way to the form and a faded-ink Cancel; focus moves into the
 * form and back to the button when it closes.
 */
export function HeaderReveal({
  label,
  children,
}: {
  label: string;
  children: (close: () => void) => ReactNode;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const formRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open) formRef.current?.querySelector<HTMLElement>("select, input, textarea")?.focus();
    else if (wasOpen.current) buttonRef.current?.focus();
    wasOpen.current = open;
  }, [open]);
  if (!open) {
    return (
      <Button
        ref={buttonRef}
        type="button"
        size="sm"
        variant="secondary"
        aria-expanded={false}
        onClick={() => setOpen(true)}
      >
        {label}
      </Button>
    );
  }
  const close = () => setOpen(false);
  return (
    <div
      ref={formRef}
      className="flex flex-wrap items-center gap-2"
      onKeyDown={(e) => {
        if (e.key === "Escape") close();
      }}
    >
      {children(close)}
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="text-muted-foreground"
        onClick={close}
      >
        {t("common.cancel")}
      </Button>
    </div>
  );
}
