import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Button,
  buttonClass,
  DataGrid,
  ErrorFallback,
  PageHeader,
  SelectField,
  TextField,
  type ColumnDef,
} from "@tutortrack/ui";
import { Link } from "@tanstack/react-router";
import { useMemo, useState, type ReactNode } from "react";

import { api, usePermission } from "../api";
import { useCursorList } from "../lists";
import { actionLink, selectionColumn, useFigures, useSelection } from "./listHelpers";
import { BulkBar, ExportLinks } from "./listTools";
import { CLIENT_STATUSES, STUDENT_STATUSES, TUTOR_STATUSES } from "./statuses";

type Client = components["schemas"]["Client"];
type Student = components["schemas"]["Student"];
type Tutor = components["schemas"]["Tutor"];

interface ListFilters {
  q: string;
  status: string;
  ordering: string;
  upcoming: string;
  owing: boolean;
}

const EMPTY: ListFilters = { q: "", status: "", ordering: "", upcoming: "", owing: false };

/** Search box, status filter, sort order and the computed-field filters (FR-05-11). */
function Filters({
  label,
  statuses,
  statusPrefix,
  sorts,
  computed,
  onApply,
}: {
  label: string;
  statuses: readonly string[];
  statusPrefix: string;
  sorts: [string, string][];
  computed?: { upcoming?: boolean; owing?: boolean };
  onApply: (filters: ListFilters) => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<ListFilters>(EMPTY);
  return (
    <form
      role="search"
      aria-label={label}
      className="mb-4 flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        onApply(draft);
      }}
    >
      <div className="min-w-56 flex-1">
        <TextField
          label={t("people.search")}
          hideLabel
          size="sm"
          placeholder={t("people.search")}
          className="min-w-56"
          type="search"
          value={draft.q}
          onChange={(e) => setDraft((d) => ({ ...d, q: e.target.value }))}
        />
      </div>
      <SelectField
        label={t("people.status")}
        hideLabel
        size="sm"
        value={draft.status}
        onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value }))}
        options={[
          { value: "", label: t("people.anyStatus") },
          ...statuses.map((s) => ({ value: s, label: t(`${statusPrefix}.${s}`) })),
        ]}
      />
      <SelectField
        label={t("peopleTools.sort.label")}
        hideLabel
        size="sm"
        value={draft.ordering}
        onChange={(e) => setDraft((d) => ({ ...d, ordering: e.target.value }))}
        options={[
          { value: "", label: t("peopleTools.sort.newest") },
          ...sorts.map(([value, key]) => ({ value, label: t(`peopleTools.sort.${key}`) })),
        ]}
      />
      {computed?.upcoming ? (
        <SelectField
          label={t("peopleTools.filters.upcoming")}
          hideLabel
          size="sm"
          value={draft.upcoming}
          onChange={(e) => setDraft((d) => ({ ...d, upcoming: e.target.value }))}
          options={[
            { value: "", label: t("peopleTools.filters.upcomingAny") },
            { value: "true", label: t("peopleTools.filters.yes") },
            { value: "false", label: t("peopleTools.filters.no") },
          ]}
        />
      ) : null}
      {computed?.owing ? (
        <label className="flex h-9 items-center gap-2 px-1 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={draft.owing}
            onChange={(e) => setDraft((d) => ({ ...d, owing: e.target.checked }))}
          />
          {t("peopleTools.filters.owing")}
        </label>
      ) : null}
      <Button type="submit" variant="secondary" size="sm" className="h-9">
        {t("people.apply")}
      </Button>
    </form>
  );
}

/** Query parameters for the list and its exports. */
function clean(filters: ListFilters): Record<string, string> {
  return {
    ...(filters.q ? { q: filters.q } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.ordering ? { ordering: filters.ordering } : {}),
    ...(filters.upcoming ? { has_upcoming_lesson: filters.upcoming } : {}),
    ...(filters.owing ? { balance_min: "0.01" } : {}),
  };
}

function ListShell<T>({
  title,
  rows,
  columns,
  query,
  getRowId,
  actions,
  children,
}: {
  actions?: ReactNode;
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
      <PageHeader title={title} actions={actions} />
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

function useSelectionLabels() {
  const { t } = useTranslation();
  return {
    all: t("peopleTools.columns.selectAll"),
    row: (name: string) => t("peopleTools.columns.selectRow", { name }),
  };
}

export function ClientsPage() {
  const { t } = useTranslation();
  const figures = useFigures();
  const labels = useSelectionLabels();
  const canCreate = usePermission("people.client.create");
  const canExport = usePermission("people.client.export");
  const canMerge = usePermission("people.merge");
  const selection = useSelection();
  const [filters, setFilters] = useState<ListFilters>(EMPTY);
  const params = clean(filters);
  const { query, rows } = useCursorList<Client>(["clients", params], async (cursor) =>
    unwrap(
      await api.GET("/api/v1/clients", {
        params: {
          query: {
            ...params,
            status: params.status as (typeof CLIENT_STATUSES)[number] | undefined,
            cursor,
          },
        },
      }),
    ),
  );
  const columns = useMemo<ColumnDef<Client, unknown>[]>(
    () => [
      selectionColumn(
        selection,
        rows,
        (r) => r.id,
        (r) => r.display_name,
        labels,
      ),
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
        header: t("people.status"),
        accessorKey: "status",
        cell: ({ getValue }) => t(`people.clientStatus.${String(getValue())}`),
      },
      { header: t("people.students"), accessorKey: "students_count" },
      {
        header: t("peopleTools.columns.balance"),
        id: "balance",
        cell: ({ row }) => figures.money(row.original.balance, row.original.currency),
      },
      {
        header: t("peopleTools.columns.nextLesson"),
        id: "next",
        cell: ({ row }) => figures.date(row.original.next_lesson_at),
      },
      {
        header: t("peopleTools.columns.lastLesson"),
        id: "last",
        cell: ({ row }) => figures.date(row.original.last_lesson_at),
      },
      {
        header: t("peopleTools.columns.hoursThisTerm"),
        id: "hours",
        cell: ({ row }) => figures.hours(row.original.hours_this_term),
      },
    ],
    [t, figures, rows, selection, labels],
  );
  return (
    <ListShell
      title={t("people.clients")}
      rows={rows}
      columns={columns}
      query={query}
      getRowId={(r) => r.id}
      actions={
        <>
          {canMerge ? (
            <Link className={actionLink} to="/people/duplicates">
              {t("peopleTools.duplicates.nav")}
            </Link>
          ) : null}
          {canExport ? <ExportLinks path="/api/v1/clients/export" params={params} /> : null}
          {canCreate ? (
            <Link className={buttonClass()} to="/clients/new">
              {t("people.quickAdd.title")}
            </Link>
          ) : null}
        </>
      }
    >
      <Filters
        label={t("people.clients")}
        statuses={CLIENT_STATUSES}
        statusPrefix="people.clientStatus"
        sorts={[
          ["display_name", "name"],
          ["-balance", "balance"],
          ["next_lesson_at", "nextLesson"],
          ["last_lesson_at", "lastLesson"],
          ["-hours_this_term", "hoursThisTerm"],
        ]}
        computed={{ upcoming: true, owing: true }}
        onApply={setFilters}
      />
      <BulkBar entity="client" selection={selection} mergeEntity="clients" />
    </ListShell>
  );
}

export function StudentsPage() {
  const { t } = useTranslation();
  const figures = useFigures();
  const labels = useSelectionLabels();
  const canExport = usePermission("people.student.export");
  const selection = useSelection();
  const [filters, setFilters] = useState<ListFilters>(EMPTY);
  const params = clean(filters);
  const { query, rows } = useCursorList<Student>(["students", params], async (cursor) =>
    unwrap(
      await api.GET("/api/v1/students", {
        params: {
          query: {
            ...params,
            status: params.status
              ? [params.status as (typeof STUDENT_STATUSES)[number]]
              : undefined,
            cursor,
          },
        },
      }),
    ),
  );
  const columns = useMemo<ColumnDef<Student, unknown>[]>(
    () => [
      selectionColumn(
        selection,
        rows,
        (r) => r.id,
        (r) => r.full_name ?? "",
        labels,
      ),
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
      {
        header: t("peopleTools.columns.nextLesson"),
        id: "next",
        cell: ({ row }) => figures.date(row.original.next_lesson_at),
      },
      {
        header: t("peopleTools.columns.hoursThisTerm"),
        id: "hours",
        cell: ({ row }) => figures.hours(row.original.hours_this_term),
      },
    ],
    [t, figures, rows, selection, labels],
  );
  return (
    <ListShell
      title={t("people.studentsTitle")}
      rows={rows}
      columns={columns}
      query={query}
      getRowId={(r) => r.id}
      actions={canExport ? <ExportLinks path="/api/v1/students/export" params={params} /> : null}
    >
      <Filters
        label={t("people.studentsTitle")}
        statuses={STUDENT_STATUSES}
        statusPrefix="people.studentStatus"
        sorts={[
          ["last_name", "name"],
          ["next_lesson_at", "nextLesson"],
          ["last_lesson_at", "lastLesson"],
          ["-hours_this_term", "hoursThisTerm"],
        ]}
        computed={{ upcoming: true }}
        onApply={setFilters}
      />
      <BulkBar entity="student" selection={selection} mergeEntity="students" />
    </ListShell>
  );
}

export function TutorsPage() {
  const { t } = useTranslation();
  const figures = useFigures();
  const labels = useSelectionLabels();
  const canExport = usePermission("people.tutor.export");
  const selection = useSelection();
  const [filters, setFilters] = useState<ListFilters>(EMPTY);
  const params = clean(filters);
  const { query, rows } = useCursorList<Tutor>(["tutors", params], async (cursor) =>
    unwrap(
      await api.GET("/api/v1/tutors", {
        params: {
          query: {
            ...params,
            status: params.status ? [params.status as (typeof TUTOR_STATUSES)[number]] : undefined,
            cursor,
          },
        },
      }),
    ),
  );
  const columns = useMemo<ColumnDef<Tutor, unknown>[]>(
    () => [
      selectionColumn(
        selection,
        rows,
        (r) => r.id,
        (r) => r.full_name,
        labels,
      ),
      {
        header: t("people.name"),
        accessorKey: "full_name",
        cell: ({ row }) => (
          <Link className={linkClass} to="/tutors/$tutorId" params={{ tutorId: row.original.id }}>
            {row.original.full_name}
          </Link>
        ),
      },
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
      {
        header: t("peopleTools.columns.hoursThisMonth"),
        id: "hours",
        cell: ({ row }) => figures.hours(row.original.hours_this_month),
      },
      {
        header: t("peopleTools.columns.utilisation"),
        id: "utilisation",
        cell: ({ row }) => figures.percent(row.original.utilisation),
      },
      {
        header: t("peopleTools.columns.reportSla"),
        id: "sla",
        cell: ({ row }) => figures.percent(row.original.report_sla),
      },
    ],
    [t, figures, rows, selection, labels],
  );
  return (
    <ListShell
      title={t("people.tutorsTitle")}
      rows={rows}
      columns={columns}
      query={query}
      getRowId={(r) => r.id}
      actions={canExport ? <ExportLinks path="/api/v1/tutors/export" params={params} /> : null}
    >
      <Filters
        label={t("people.tutorsTitle")}
        statuses={TUTOR_STATUSES}
        statusPrefix="people.tutorStatus"
        sorts={[
          ["last_name", "name"],
          ["-hours_this_month", "hoursThisMonth"],
          ["report_sla", "reportSla"],
        ]}
        onApply={setFilters}
      />
      <BulkBar entity="tutor" selection={selection} />
    </ListShell>
  );
}
