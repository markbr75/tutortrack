import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { DataGrid, ErrorFallback, type ColumnDef } from "@tutortrack/ui";
import { Button, TextField } from "@tutortrack/ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, usePermission } from "../api";

type AuditEntry = components["schemas"]["AuditEntry"];

function cursorFrom(next: string | null | undefined): string | undefined {
  return next
    ? (new URL(next, window.location.origin).searchParams.get("cursor") ?? undefined)
    : undefined;
}

/** Reference implementation of a list screen: cursor pagination + DataGrid. */
interface Filters {
  q: string;
  actor_email: string;
  action: string;
  created_after: string;
  created_before: string;
}

const EMPTY: Filters = { q: "", actor_email: "", action: "", created_after: "", created_before: "" };

/** Only the filters that are set, with dates as ISO timestamps. */
function activeFilters(filters: Filters): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (!value) continue;
    out[key] = key.startsWith("created_") ? new Date(value).toISOString() : value;
  }
  return out;
}

export function AuditPage() {
  const { t, i18n } = useTranslation();
  const canExport = usePermission("audit.export");
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const params = activeFilters(filters);
  const query = useInfiniteQuery({
    queryKey: ["audit", params],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/audit", { params: { query: { ...params, cursor: pageParam } } }),
      ),
    getNextPageParam: (page) => cursorFrom(page.next),
  });
  const exportUrl = `/api/v1/audit/export?${new URLSearchParams(params).toString()}`;
  const field = (name: keyof Filters, label: string, type = "text") => (
    <TextField
      label={label}
      type={type}
      value={draft[name]}
      onChange={(e) => setDraft((d) => ({ ...d, [name]: e.target.value }))}
    />
  );

  const columns = useMemo<ColumnDef<AuditEntry, unknown>[]>(
    () => [
      {
        header: t("audit.when"),
        accessorKey: "created_at",
        cell: ({ getValue }) => formatDateTime(String(getValue()), i18n.language),
      },
      { header: t("audit.action"), accessorKey: "action" },
      { header: t("audit.actor"), accessorKey: "actor_email" },
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
      <form
        role="search"
        aria-label={t("audit.search")}
        className="mb-6 grid gap-3 sm:grid-cols-3 lg:grid-cols-6 lg:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters(draft);
        }}
      >
        {field("q", t("audit.search"))}
        {field("actor_email", t("audit.actor"), "email")}
        {field("action", t("audit.action"))}
        {field("created_after", t("audit.from"), "date")}
        {field("created_before", t("audit.to"), "date")}
        <div className="flex gap-2">
          <Button type="submit">{t("audit.apply")}</Button>
          {canExport ? (
            <a
              className="inline-flex h-10 items-center rounded-md border border-border px-4 text-sm hover:bg-muted"
              href={exportUrl}
            >
              {t("audit.export")}
            </a>
          ) : null}
        </div>
      </form>
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
