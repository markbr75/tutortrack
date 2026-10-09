import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Button,
  DataGrid,
  ErrorFallback,
  SelectField,
  Spinner,
  TextField,
  type ColumnDef,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { api, usePermission } from "../api";
import { useCursorList } from "../lists";
import { BOARD_STATUSES, JOB_STATUSES, NEXT_STATUSES, type JobStatus } from "./statuses";

type Job = components["schemas"]["Job"];

const linkClass = "font-medium underline-offset-2 hover:underline";

function tutorNames(job: Job): string {
  return job.tutors
    .filter((t) => t.status === "active" || t.status === "offered")
    .map((t) => t.tutor_name)
    .join(", ");
}

function JobList() {
  const { t } = useTranslation();
  const [draft, setDraft] = useState({ q: "", status: "", attention: false });
  const [filters, setFilters] = useState(draft);
  const params = {
    ...(filters.q ? { q: filters.q } : {}),
    ...(filters.status ? { status: [filters.status as JobStatus] } : {}),
    ...(filters.attention ? { attention: true } : {}),
  };
  const { query, rows } = useCursorList<Job>(["jobs", params], async (cursor) =>
    unwrap(await api.GET("/api/v1/jobs", { params: { query: { ...params, cursor } } })),
  );
  const columns = useMemo<ColumnDef<Job, unknown>[]>(
    () => [
      {
        header: t("jobs.job"),
        accessorKey: "name",
        cell: ({ row }) => (
          <Link className={linkClass} to="/jobs/$jobId" params={{ jobId: row.original.id }}>
            {row.original.reference} · {row.original.name}
          </Link>
        ),
      },
      { header: t("jobs.client"), accessorKey: "client_name" },
      { header: t("jobs.service"), accessorKey: "service_name" },
      { header: t("jobs.tutors"), id: "tutors", cell: ({ row }) => tutorNames(row.original) },
      {
        header: t("jobs.statusLabel"),
        accessorKey: "status",
        cell: ({ getValue }) => t(`jobs.status.${String(getValue())}`),
      },
    ],
    [t],
  );
  return (
    <>
      <form
        role="search"
        aria-label={t("jobs.title")}
        className="mb-6 grid gap-3 sm:grid-cols-[1fr_12rem_auto_auto] sm:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters(draft);
        }}
      >
        <TextField
          label={t("jobs.search")}
          type="search"
          value={draft.q}
          onChange={(e) => setDraft((d) => ({ ...d, q: e.target.value }))}
        />
        <SelectField
          label={t("jobs.statusLabel")}
          value={draft.status}
          onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value }))}
          options={[
            { value: "", label: t("people.anyStatus") },
            ...JOB_STATUSES.map((s) => ({ value: s, label: t(`jobs.status.${s}`) })),
          ]}
        />
        <label className="flex h-10 items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={draft.attention}
            onChange={(e) => setDraft((d) => ({ ...d, attention: e.target.checked }))}
          />
          {t("jobs.needsAttention")}
        </label>
        <Button type="submit">{t("people.apply")}</Button>
      </form>
      {query.isError ? (
        <ErrorFallback
          title={t("errors.generic")}
          retryLabel={t("errors.retry")}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <DataGrid
          caption={t("jobs.title")}
          rows={rows}
          columns={columns}
          getRowId={(r) => r.id}
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
    </>
  );
}

/** Kanban by status (FR-07-6). Cards move with a select, so it works without dragging. */
function JobBoard() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canChange = usePermission("jobs.job.change_status");
  const board = useQuery({
    queryKey: ["jobs", "board"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/jobs", {
          params: { query: { status: BOARD_STATUSES, page_size: 200 } },
        }),
      ),
  });
  const move = useMutation({
    mutationFn: async ({ id, status }: { id: string; status: JobStatus }) =>
      unwrap(
        await api.POST("/api/v1/jobs/{id}/status", {
          params: { path: { id } },
          body: { status, reason: "", future_lessons: "keep" },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });
  if (board.isPending) return <Spinner label={t("grid.loading")} />;
  if (board.isError) {
    return (
      <ErrorFallback
        title={t("errors.generic")}
        retryLabel={t("errors.retry")}
        onRetry={() => void board.refetch()}
      />
    );
  }
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {move.isError ? (
        <p role="alert" className="text-sm text-danger md:col-span-2 xl:col-span-4">
          {t("jobs.moveFailed")}
        </p>
      ) : null}
      {BOARD_STATUSES.map((status) => {
        const jobs = board.data.results.filter((j) => j.status === status);
        return (
          <section
            key={status}
            aria-labelledby={`col-${status}`}
            className="rounded-lg bg-muted/40 p-3"
          >
            <h2 id={`col-${status}`} className="mb-3 font-semibold">
              {t(`jobs.status.${status}`)}{" "}
              <span className="text-muted-foreground">({jobs.length})</span>
            </h2>
            <ul className="space-y-2">
              {jobs.map((job) => (
                <li
                  key={job.id}
                  className="rounded-md border border-border bg-background p-3 text-sm"
                >
                  <Link className={linkClass} to="/jobs/$jobId" params={{ jobId: job.id }}>
                    {job.name}
                  </Link>
                  <p className="text-muted-foreground">
                    {job.reference} · {tutorNames(job) || t("jobs.noTutor")}
                  </p>
                  {canChange && NEXT_STATUSES[status].length ? (
                    <SelectField
                      className="mt-2 h-8"
                      label={t("jobs.moveNamed", { name: job.name })}
                      value=""
                      onChange={(e) =>
                        e.target.value &&
                        move.mutate({ id: job.id, status: e.target.value as JobStatus })
                      }
                      options={[
                        { value: "", label: t("jobs.moveTo") },
                        ...NEXT_STATUSES[status].map((s) => ({
                          value: s,
                          label: t(`jobs.status.${s}`),
                        })),
                      ]}
                    />
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

export function JobsPage() {
  const { t } = useTranslation();
  const [view, setView] = useState<"list" | "board">("list");
  return (
    <section>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t("jobs.title")}</h1>
        <div role="group" aria-label={t("jobs.view")} className="flex gap-1">
          {(["list", "board"] as const).map((v) => (
            <Button
              key={v}
              size="sm"
              variant={view === v ? "primary" : "secondary"}
              aria-pressed={view === v}
              onClick={() => setView(v)}
            >
              {t(`jobs.views.${v}`)}
            </Button>
          ))}
        </div>
      </div>
      {view === "list" ? <JobList /> : <JobBoard />}
    </section>
  );
}
