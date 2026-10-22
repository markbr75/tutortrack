import { useTranslation } from "@tutortrack/i18n";
import { Alert, ErrorFallback, RuledTable, type RuledColumn } from "@tutortrack/ui";
import type { ReactNode } from "react";

import { fieldErrors } from "../api";

export function QueryState({
  query,
  children,
}: {
  query: { isPending: boolean; isError: boolean; refetch: () => unknown };
  children: ReactNode;
}) {
  const { t } = useTranslation();
  if (query.isError) {
    return (
      <ErrorFallback
        title={t("errors.generic")}
        retryLabel={t("errors.retry")}
        onRetry={() => void query.refetch()}
      />
    );
  }
  return <>{children}</>;
}

/** The first field error (or a generic message) for a failed mutation. */
export function MutationError({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  const errors = Object.entries(fieldErrors(error));
  return (
    <Alert tone="danger">
      {errors.length
        ? errors.map(([field, message]) => `${field}: ${message}`).join(" ")
        : t("errors.generic")}
    </Alert>
  );
}

/**
 * A catalogue list: a framed register table with skeleton rows while it loads and one
 * faded-ink sentence when it is empty.
 */
export function Table({
  caption,
  columns,
  loading,
  count,
  empty,
  framed = true,
  children,
}: {
  caption: string;
  columns: ReadonlyArray<RuledColumn>;
  loading?: boolean;
  count?: number;
  empty?: string;
  framed?: boolean;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <RuledTable
      framed={framed}
      caption={caption}
      columns={columns}
      loading={loading}
      loadingLabel={t("grid.loading")}
      empty={!loading && count === 0 ? (empty ?? t("grid.empty")) : undefined}
    >
      {children}
    </RuledTable>
  );
}

/** A secondary word in faded ink (an inactive status, an empty value). */
export function Faded({ children }: { children: ReactNode }) {
  return <span className="text-muted-foreground">{children}</span>;
}
