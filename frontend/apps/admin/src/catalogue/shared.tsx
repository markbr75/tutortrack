import { useTranslation } from "@tutortrack/i18n";
import { Alert, ErrorFallback, Spinner } from "@tutortrack/ui";
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
  if (query.isPending) return <Spinner label={t("grid.loading")} />;
  return <>{children}</>;
}

/** The first field error (or a generic message) for a failed mutation. */
export function MutationError({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  const errors = Object.entries(fieldErrors(error));
  return (
    <Alert tone="danger" className="mt-3">
      {errors.length
        ? errors.map(([field, message]) => `${field}: ${message}`).join(" ")
        : t("errors.generic")}
    </Alert>
  );
}

export function Table({
  caption,
  headers,
  children,
}: {
  caption: string;
  headers: string[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border">
            {headers.map((h) => (
              <th key={h} scope="col" className="px-2 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">{children}</tbody>
      </table>
    </div>
  );
}

export function Cell({ children }: { children: ReactNode }) {
  return <td className="px-2 py-2 align-top">{children}</td>;
}
