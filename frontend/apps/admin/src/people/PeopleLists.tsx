import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Button,
  DataGrid,
  ErrorFallback,
  SelectField,
  TextField,
  type ColumnDef,
} from "@tutortrack/ui";
import { Link } from "@tanstack/react-router";
import { useMemo, useState, type ReactNode } from "react";

import { api, usePermission } from "../api";
import { useCursorList } from "../lists";
import { CLIENT_STATUSES, STUDENT_STATUSES, TUTOR_STATUSES } from "./statuses";

type Client = components["schemas"]["Client"];
type Student = components["schemas"]["Student"];
type Tutor = components["schemas"]["Tutor"];

interface ListFilters {
  q: string;
  status: string;
}

/** Search box + status filter shared by the people lists. */
function Filters({
  label,
  statuses,
  statusPrefix,
  onApply,
  actions,
}: {
  label: string;
  statuses: readonly string[];
  statusPrefix: string;
  onApply: (filters: ListFilters) => void;
  actions?: ReactNode;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<ListFilters>({ q: "", status: "" });
  return (
    <form
      role="search"
      aria-label={label}
      className="mb-6 grid gap-3 sm:grid-cols-[1fr_12rem_auto] sm:items-end"
      onSubmit={(e) => {
        e.preventDefault();
        onApply(draft);
      }}
    >
      <TextField
        label={t("people.search")}
        type="search"
        value={draft.q}
        onChange={(e) => setDraft((d) => ({ ...d, q: e.target.value }))}
      />
      <SelectField
        label={t("people.status")}
        value={draft.status}
        onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value }))}
        options={[
          { value: "", label: t("people.anyStatus") },
          ...statuses.map((s) => ({ value: s, label: t(`${statusPrefix}.${s}`) })),
        ]}
      />
      <div className="flex flex-wrap gap-2">
        <Button type="submit">{t("people.apply")}</Button>
        {actions}
      </div>
    </form>
  );
}

function clean<S extends string>(filters: ListFilters): { q?: string; status?: S } {
  return {
    ...(filters.q ? { q: filters.q } : {}),
    ...(filters.status ? { status: filters.status as S } : {}),
  };
}

function ListShell<T>({
  title,
  rows,
  columns,
  query,
  getRowId,
  children,
}: {
  title: string;
  rows: T[];
  columns: ColumnDef<T, unknown>[];
  query: ReturnType<typeof useCursorList<T>>["query"];
  getRowId: (row: T) => string;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">{title}</h1>
      {children}
      {query.isError ? (
        <ErrorFallback
          title={t("errors.generic")}
          retryLabel={t("errors.retry")}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <DataGrid
          caption={title}
          rows={rows}
          columns={columns}
          getRowId={getRowId}
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
      )}
    </section>
  );
}

const linkClass = "font-medium underline-offset-2 hover:underline";
const actionLink =
  "inline-flex h-10 items-center rounded-md border border-border px-4 text-sm hover:bg-muted";

export function ClientsPage() {
  const { t } = useTranslation();
  const canCreate = usePermission("people.client.create");
  const canExport = usePermission("people.client.export");
  const [filters, setFilters] = useState<ListFilters>({ q: "", status: "" });
  const params = clean<(typeof CLIENT_STATUSES)[number]>(filters);
  const { query, rows } = useCursorList<Client>(["clients", params], async (cursor) =>
    unwrap(await api.GET("/api/v1/clients", { params: { query: { ...params, cursor } } })),
  );
  const columns = useMemo<ColumnDef<Client, unknown>[]>(
    () => [
      {
        header: t("people.name"),
        accessorKey: "display_name",
        cell: ({ row }) => (
          <Link
            className={linkClass}
            to="/clients/$clientId"
            params={{ clientId: row.original.id }}
          >
            {row.original.display_name}
          </Link>
        ),
      },
      {
        header: t("people.type"),
        accessorKey: "type",
        cell: ({ getValue }) => t(`people.clientType.${String(getValue())}`),
      },
      {
        header: t("people.status"),
        accessorKey: "status",
        cell: ({ getValue }) => t(`people.clientStatus.${String(getValue())}`),
      },
      { header: t("people.students"), accessorKey: "students_count" },
    ],
    [t],
  );
  return (
    <ListShell
      title={t("people.clients")}
      rows={rows}
      columns={columns}
      query={query}
      getRowId={(r) => r.id}
    >
      <Filters
        label={t("people.clients")}
        statuses={CLIENT_STATUSES}
        statusPrefix="people.clientStatus"
        onApply={setFilters}
        actions={
          <>
            {canCreate ? (
              <Link className={actionLink} to="/clients/new">
                {t("people.quickAdd.title")}
              </Link>
            ) : null}
            {canExport ? (
              <a
                className={actionLink}
                href={`/api/v1/clients/export?${new URLSearchParams(params).toString()}`}
              >
                {t("people.export")}
              </a>
            ) : null}
          </>
        }
      />
    </ListShell>
  );
}

export function StudentsPage() {
  const { t } = useTranslation();
  const [filters, setFilters] = useState<ListFilters>({ q: "", status: "" });
  const params = clean<(typeof STUDENT_STATUSES)[number]>(filters);
  const { query, rows } = useCursorList<Student>(["students", params], async (cursor) =>
    unwrap(
      await api.GET("/api/v1/students", {
        params: {
          query: { q: params.q, status: params.status ? [params.status] : undefined, cursor },
        },
      }),
    ),
  );
  const columns = useMemo<ColumnDef<Student, unknown>[]>(
    () => [
      {
        header: t("people.name"),
        accessorKey: "full_name",
        cell: ({ row }) => (
          <Link
            className={linkClass}
            to="/students/$studentId"
            params={{ studentId: row.original.id }}
          >
            {row.original.full_name}
          </Link>
        ),
      },
      { header: t("people.yearGroup"), accessorKey: "year_group" },
      {
        header: t("people.subjects"),
        id: "subjects",
        cell: ({ row }) =>
          (row.original.subjects ?? [])
            .map((s) => [s.subject, s.level].filter(Boolean).join(" "))
            .join(", "),
      },
      {
        header: t("people.status"),
        accessorKey: "status",
        cell: ({ getValue }) => t(`people.studentStatus.${String(getValue())}`),
      },
    ],
    [t],
  );
  return (
    <ListShell
      title={t("people.studentsTitle")}
      rows={rows}
      columns={columns}
      query={query}
      getRowId={(r) => r.id}
    >
      <Filters
        label={t("people.studentsTitle")}
        statuses={STUDENT_STATUSES}
        statusPrefix="people.studentStatus"
        onApply={setFilters}
      />
    </ListShell>
  );
}

export function TutorsPage() {
  const { t } = useTranslation();
  const [filters, setFilters] = useState<ListFilters>({ q: "", status: "" });
  const params = clean<(typeof TUTOR_STATUSES)[number]>(filters);
  const { query, rows } = useCursorList<Tutor>(["tutors", params], async (cursor) =>
    unwrap(
      await api.GET("/api/v1/tutors", {
        params: {
          query: { q: params.q, status: params.status ? [params.status] : undefined, cursor },
        },
      }),
    ),
  );
  const columns = useMemo<ColumnDef<Tutor, unknown>[]>(
    () => [
      {
        header: t("people.name"),
        accessorKey: "full_name",
        cell: ({ row }) => (
          <Link className={linkClass} to="/tutors/$tutorId" params={{ tutorId: row.original.id }}>
            {row.original.full_name}
          </Link>
        ),
      },
      { header: t("people.email"), accessorKey: "email" },
      {
        header: t("people.subjects"),
        id: "subjects",
        cell: ({ row }) => row.original.subjects.map((s) => s.subject).join(", "),
      },
      {
        header: t("people.status"),
        accessorKey: "status",
        cell: ({ getValue }) => t(`people.tutorStatus.${String(getValue())}`),
      },
    ],
    [t],
  );
  return (
    <ListShell
      title={t("people.tutorsTitle")}
      rows={rows}
      columns={columns}
      query={query}
      getRowId={(r) => r.id}
    >
      <Filters
        label={t("people.tutorsTitle")}
        statuses={TUTOR_STATUSES}
        statusPrefix="people.tutorStatus"
        onApply={setFilters}
      />
    </ListShell>
  );
}
