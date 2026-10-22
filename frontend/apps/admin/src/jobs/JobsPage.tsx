import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Button,
  DataGrid,
  ErrorFallback,
  NamePlate,
  PageHeader,
  Segmented,
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
import { ATTENTION_REASONS, AttentionReasons, type AttentionReason } from "../g3/JobAttention";
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
  const [draft, setDraft] = useState({ q: "", status: "", attention: false, reason: "" });
  const [filters, setFilters] = useState(draft);
  const params = {
    ...(filters.q ? { q: filters.q } : {}),
    ...(filters.status ? { status: [filters.status as JobStatus] } : {}),
    ...(filters.attention && !filters.reason ? { attention: true } : {}),
    ...(filters.reason ? { attention_reason: filters.reason as AttentionReason } : {}),
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
          <NamePlate
            name={
              <Link className={linkClass} to="/jobs/$jobId" params={{ jobId: row.original.id }}>
                {row.original.name}
              </Link>
            }
            context={row.original.reference}
          />
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
      {
        header: t("g3.attention.column"),
        id: "attention",
        cell: ({ row }) => <AttentionReasons reasons={row.original.attention_reasons} />,
      },
    ],
    [t],
  );
  return (
    <>
      <form
        role="search"
        aria-label={t("jobs.title")}
        className="mb-4 flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters(draft);
        }}
      >
        <div className="min-w-56 flex-1">
          <TextField
            label={t("jobs.search")}
            hideLabel
            size="sm"
            placeholder={t("jobs.search")}
            type="search"
            value={draft.q}
            onChange={(e) => setDraft((d) => ({ ...d, q: e.target.value }))}
          />
        </div>
        <SelectField
          label={t("jobs.statusLabel")}
          hideLabel
          size="sm"
          value={draft.status}
          onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value }))}
          options={[
            { value: "", label: t("people.anyStatus") },
            ...JOB_STATUSES.map((s) => ({ value: s, label: t(`jobs.status.${s}`) })),
          ]}
        />
        <label className="flex h-9 items-center gap-2 px-1 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={draft.attention}
            onChange={(e) => setDraft((d) => ({ ...d, attention: e.target.checked }))}
          />
          {t("jobs.needsAttention")}
        </label>
        <SelectField
          label={t("g3.attention.reason")}
          hideLabel
          size="sm"
          value={draft.reason}
          onChange={(e) => setDraft((d) => ({ ...d, reason: e.target.value }))}
          options={[
            { value: "", label: t("g3.attention.anyReason") },
            ...ATTENTION_REASONS.map((r) => ({ value: r, label: t(`g3.attention.reasons.${r}`) })),
          ]}
        />
        <Button type="submit" variant="secondary" size="sm" className="h-9">
          {t("people.apply")}
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
    <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-4">
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
            className="min-w-0 rounded-xl border border-border bg-surface"
          >
            <h2
              id={`col-${status}`}
              className="flex items-baseline justify-between gap-2 border-b border-border px-4 py-3 text-base font-semibold"
            >
              <span>{t(`jobs.status.${status}`)}</span>{" "}
              <span className="text-sm font-normal text-muted-foreground tabular-nums">
                ({jobs.length})
              </span>
            </h2>
            {jobs.length === 0 ? (
              <p className="px-4 py-4 text-sm text-muted-foreground">
                {t("designS5.jobs.emptyColumn")}
              </p>
            ) : null}
            <ul className="divide-y divide-rule">
              {jobs.map((job) => (
                <li key={job.id} className="space-y-1.5 px-4 py-2.5 text-sm">
                  <NamePlate
                    name={
                      <Link className={linkClass} to="/jobs/$jobId" params={{ jobId: job.id }}>
                        {job.name}
                      </Link>
                    }
                    context={`${job.reference} · ${tutorNames(job) || t("jobs.noTutor")}`}
                  />
                  {canChange && NEXT_STATUSES[status].length ? (
                    <SelectField
                      className="h-8"
                      hideLabel
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
      <PageHeader
        title={t("jobs.title")}
        actions={
          <Segmented
            label={t("jobs.view")}
            value={view}
            onChange={setView}
            options={(["list", "board"] as const).map((v) => ({
              key: v,
              label: t(`jobs.views.${v}`),
            }))}
          />
        }
      />
      {view === "list" ? <JobList /> : <JobBoard />}
    </section>
  );
}
