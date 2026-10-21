import { useTranslation } from "@tutortrack/i18n";
import { PageHeader } from "@tutortrack/ui";
import { ChevronLeft } from "lucide-react";
import type { ReactNode } from "react";

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
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="min-w-0 space-y-6">{main}</div>
      <aside className="min-w-0 space-y-6">{side}</aside>
    </div>
  );
}

/** The separator between two back links. */
export function BackSeparator() {
  return <span aria-hidden="true">·</span>;
}
