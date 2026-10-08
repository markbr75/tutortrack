import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { DataGrid, ErrorFallback, type ColumnDef } from "@tutortrack/ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { api } from "../api";

type AuditEntry = components["schemas"]["AuditEntry"];

function cursorFrom(next: string | null | undefined): string | undefined {
  return next
    ? (new URL(next, window.location.origin).searchParams.get("cursor") ?? undefined)
    : undefined;
}

/** Reference implementation of a list screen: cursor pagination + DataGrid. */
export function AuditPage() {
  const { t, i18n } = useTranslation();
  const query = useInfiniteQuery({
    queryKey: ["audit"],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(await api.GET("/api/v1/audit", { params: { query: { cursor: pageParam } } })),
    getNextPageParam: (page) => cursorFrom(page.next),
  });

  const columns = useMemo<ColumnDef<AuditEntry, unknown>[]>(
    () => [
      {
        header: t("audit.when"),
        accessorKey: "created_at",
        cell: ({ getValue }) => formatDateTime(String(getValue()), i18n.language),
      },
      { header: t("audit.action"), accessorKey: "action" },
      {
        header: t("audit.object"),
        id: "object",
        cell: ({ row }) => `${row.original.object_type} · ${row.original.object_repr}`,
      },
      {
        header: t("audit.changes"),
        accessorKey: "changes",
        cell: ({ getValue }) => (
          <code className="text-xs break-all">{JSON.stringify(getValue())}</code>
        ),
      },
    ],
    [t, i18n.language],
  );

  if (query.isError) {
    return (
      <ErrorFallback
        title={t("errors.generic")}
        retryLabel={t("errors.retry")}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const rows = query.data?.pages.flatMap((page) => page.results) ?? [];
  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">{t("audit.title")}</h1>
      <DataGrid
        caption={t("audit.title")}
        rows={rows}
        columns={columns}
        getRowId={(row) => row.id}
        isLoading={query.isPending}
        hasMore={query.hasNextPage}
        isFetchingMore={query.isFetchingNextPage}
        onLoadMore={() => void query.fetchNextPage()}
        labels={{
          loading: t("grid.loading"),
          empty: t("grid.empty"),
          loadMore: t("grid.loadMore"),
        }}
      />
    </section>
  );
}
