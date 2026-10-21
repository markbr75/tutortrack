import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { DataGrid, PageHeader, Tabs, type ColumnDef } from "@tutortrack/ui";
import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { api, usePermission } from "../api";
import { useCursorList } from "../lists";

type Sla = "due" | "overdue" | "awaiting_approval" | "shared";
export type LessonReport = components["schemas"]["LessonReport"];

/** "Reports due" and the review queue (FR-09-5..7). Tutors see their own reports. */
export function ReportsPage() {
  const { t, i18n } = useTranslation();
  const canApprove = usePermission("delivery.report.approve");
  const [tab, setTab] = useState<Sla>("due");
  const tabs: Sla[] = canApprove
    ? ["due", "overdue", "awaiting_approval", "shared"]
    : ["due", "overdue", "shared"];
  const list = useCursorList(["lesson-reports", tab], async (cursor) =>
    unwrap(await api.GET("/api/v1/lesson-reports", { params: { query: { sla: tab, cursor } } })),
  );

  const columns = useMemo<ColumnDef<LessonReport, unknown>[]>(
    () => [
      {
        id: "lesson",
        header: t("delivery.reports.lesson"),
        cell: ({ row }) => (
          <div className="min-w-48">
            <Link
              to="/reports/$reportId"
              params={{ reportId: row.original.id }}
              className="font-medium underline-offset-2 hover:text-link hover:underline"
            >
              {row.original.lesson_title}
            </Link>
            <span className="block text-xs text-muted-foreground tabular-nums">
              {formatDateTime(row.original.lesson_start, i18n.language)}
            </span>
          </div>
        ),
      },
      {
        id: "tutor",
        header: t("delivery.reports.tutor"),
        cell: ({ row }) => row.original.tutor_name,
      },
      {
        id: "due",
        header: t("delivery.reports.due"),
        cell: ({ row }) => (
          <time dateTime={row.original.due_at} className="whitespace-nowrap tabular-nums">
            {formatDateTime(row.original.due_at, i18n.language)}
          </time>
        ),
      },
      {
        id: "state",
        header: t("delivery.reports.state"),
        cell: ({ row }) => (
          <span
            className={
              row.original.sla_state === "overdue" ? "font-semibold text-margin" : undefined
            }
          >
            {t(`delivery.reports.sla.${row.original.sla_state}`)}
          </span>
        ),
      },
    ],
    [t, i18n.language],
  );

  return (
    <div>
      <PageHeader title={t("delivery.reports.title")} />
      <Tabs
        label={t("delivery.reports.title")}
        value={tab}
        onChange={setTab}
        tabs={tabs.map((key) => ({ key, label: t(`delivery.reports.tabs.${key}`) }))}
      >
        <DataGrid
          caption={t(`delivery.reports.tabs.${tab}`)}
          rows={list.rows}
          columns={columns}
          getRowId={(r) => r.id}
          isLoading={list.query.isPending}
          hasMore={list.query.hasNextPage}
          isFetchingMore={list.query.isFetchingNextPage}
          onLoadMore={() => void list.query.fetchNextPage()}
          labels={{
            loading: t("grid.loading"),
            empty: t("delivery.reports.empty"),
            loadMore: t("grid.loadMore"),
          }}
        />
      </Tabs>
    </div>
  );
}
