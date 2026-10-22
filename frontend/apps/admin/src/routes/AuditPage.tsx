import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Button,
  buttonClass,
  DataGrid,
  ErrorFallback,
  PageHeader,
  TextField,
  type ColumnDef,
} from "@tutortrack/ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, usePermission } from "../api";
import { useIsPhone } from "../billing/useIsPhone";
import { cursorFrom } from "../lists";

type AuditEntry = components["schemas"]["AuditEntry"];

interface Filters {
  q: string;
  actor_email: string;
  action: string;
  created_after: string;
  created_before: string;
}

const EMPTY: Filters = {
  q: "",
  actor_email: "",
  action: "",
  created_after: "",
  created_before: "",
};

/** Only the filters that are set, with dates as ISO timestamps. */
function activeFilters(filters: Filters): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (!value) continue;
    out[key] = key.startsWith("created_") ? new Date(value).toISOString() : value;
  }
  return out;
}

/** "status_change" → "Status change": the fallback for actions without a translation. */
function humanise(code: string): string {
  const words = code.replace(/[._]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function shown(value: unknown): string {
  if (value === null || value === undefined || value === "") return "–";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length > 40 ? `${text.slice(0, 39)}…` : text;
}

/** What changed, one "field: before → after" line each (the first six). */
function Changes({ changes }: { changes: unknown }) {
  const { t } = useTranslation();
  if (!changes || typeof changes !== "object") return null;
  const entries = Object.entries(changes as Record<string, unknown>);
  if (!entries.length) return null;
  return (
    <ul className="space-y-0.5 text-xs text-muted-foreground [overflow-wrap:anywhere]">
      {entries.slice(0, 6).map(([field, pair]) => (
        <li key={field}>
          <span className="text-foreground">{field}</span>{" "}
          {Array.isArray(pair) && pair.length === 2
            ? `${shown(pair[0])} → ${shown(pair[1])}`
            : shown(pair)}
        </li>
      ))}
      {entries.length > 6 ? (
        <li>{t("designS9b.audit.more", { count: entries.length - 6 })}</li>
      ) : null}
    </ul>
  );
}

export function AuditPage() {
  const { t, i18n } = useTranslation();
  const canExport = usePermission("audit.export");
  const phone = useIsPhone();
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
  const text = (name: keyof Filters, label: string, type = "text") => (
    <TextField
      label={label}
      hideLabel
      size="sm"
      placeholder={label}
      type={type}
      value={draft[name]}
      onChange={(e) => setDraft((d) => ({ ...d, [name]: e.target.value }))}
    />
  );
  const date = (name: keyof Filters, label: string) => (
    <label className="flex h-9 items-center gap-2 text-sm text-muted-foreground">
      {label}
      <input
        type="date"
        className="h-9 rounded-md border border-field bg-surface px-2 text-sm text-foreground tabular-nums"
        value={draft[name]}
        onChange={(e) => setDraft((d) => ({ ...d, [name]: e.target.value }))}
      />
    </label>
  );
  // The API sends readable labels (action, record type, record); older responses without
  // them fall back to the translated or humanised codes and the recorded description.
  const action = (entry: AuditEntry) =>
    entry.action_label ||
    t(`designS9b.audit.actions.${entry.action}`, { defaultValue: humanise(entry.action) });
  const objectType = (entry: AuditEntry) =>
    entry.record_type_label ||
    t(`designS9b.audit.objects.${entry.object_type}`, {
      defaultValue: humanise(entry.object_type.split(".").pop() ?? entry.object_type),
    });
  const record = (entry: AuditEntry) => entry.record_label || entry.object_repr;

  const columns = useMemo<ColumnDef<AuditEntry, unknown>[]>(
    () => [
      {
        id: "action",
        header: t("audit.action"),
        cell: ({ row }) => (
          <div className="min-w-32">
            <span className="block font-medium whitespace-nowrap">
              {action(row.original)}
            </span>
            {/* Who and when fold into one caption under the action (and, on phones, the
                record). Each part stays whole, so the line only wraps at a separator. */}
            <span className="block text-xs text-muted-foreground tabular-nums">
              <span className="whitespace-nowrap">
                {row.original.actor_email || t("designS9b.audit.system")}
              </span>
              {" · "}
              <span className="whitespace-nowrap">
                {formatDateTime(row.original.created_at, i18n.language)}
              </span>
              {phone && record(row.original) ? (
                <>
                  {" · "}
                  <span className="[overflow-wrap:anywhere]">{record(row.original)}</span>
                </>
              ) : null}
            </span>
          </div>
        ),
      },
      {
        id: "object",
        header: t("audit.object"),
        cell: ({ row }) => (
          <div className="min-w-28">
            <span className="block [overflow-wrap:anywhere]">{record(row.original)}</span>
            <span className="block text-xs text-muted-foreground">
              {objectType(row.original)}
            </span>
          </div>
        ),
      },
      {
        id: "changes",
        header: t("audit.changes"),
        cell: ({ row }) => (
          <div className="max-w-sm min-w-40">
            <Changes changes={row.original.changes} />
          </div>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- action/objectType/record follow t
    [t, i18n.language, phone],
  );

  const rows = query.data?.pages.flatMap((page) => page.results) ?? [];
  return (
    <section>
      <PageHeader
        title={t("audit.title")}
        description={t("designS9b.audit.description")}
        actions={
          canExport ? (
            <a className={buttonClass({ variant: "secondary", size: "sm" })} href={exportUrl}>
              {t("audit.export")}
            </a>
          ) : null
        }
      />
      <form
        role="search"
        aria-label={t("audit.search")}
        className="mb-4 flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters(draft);
        }}
      >
        <div className="min-w-56 flex-1">{text("q", t("audit.search"), "search")}</div>
        <div className="w-full sm:w-56">{text("actor_email", t("audit.actor"), "email")}</div>
        <div className="w-full sm:w-44">{text("action", t("audit.action"))}</div>
        {date("created_after", t("audit.from"))}
        {date("created_before", t("audit.to"))}
        <Button type="submit" variant="secondary" size="sm" className="h-9">
          {t("audit.apply")}
        </Button>
      </form>
      {query.isError ? (
        <ErrorFallback
          title={t("errors.generic")}
          retryLabel={t("errors.retry")}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <DataGrid
          key={phone ? "phone" : "wide"}
          caption={t("audit.title")}
          rows={rows}
          columns={columns}
          getRowId={(row) => row.id}
          isLoading={query.isPending}
          hasMore={query.hasNextPage}
          isFetchingMore={query.isFetchingNextPage}
          onLoadMore={() => void query.fetchNextPage()}
          initialColumnVisibility={
            phone ? { when: false, object: false, changes: false } : undefined
          }
          labels={{
            loading: t("grid.loading"),
            empty: t("designS9b.audit.empty"),
            loadMore: t("grid.loadMore"),
          }}
        />
      )}
    </section>
  );
}
