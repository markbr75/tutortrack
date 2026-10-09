import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Button, Spinner, Tabs } from "@tutortrack/ui";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

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

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("delivery.reports.title")}</h1>
      <Tabs
        label={t("delivery.reports.title")}
        value={tab}
        onChange={setTab}
        tabs={tabs.map((key) => ({ key, label: t(`delivery.reports.tabs.${key}`) }))}
      >
        {list.query.isPending ? (
          <Spinner className="size-5" label={t("grid.loading")} />
        ) : list.rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("delivery.reports.empty")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="py-2 pr-4">
                    {t("delivery.reports.lesson")}
                  </th>
                  <th scope="col" className="py-2 pr-4">
                    {t("delivery.reports.tutor")}
                  </th>
                  <th scope="col" className="py-2 pr-4">
                    {t("delivery.reports.due")}
                  </th>
                  <th scope="col" className="py-2 pr-4">
                    {t("delivery.reports.state")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.rows.map((report) => (
                  <tr key={report.id} className="border-b border-border">
                    <td className="py-2 pr-4">
                      <Link
                        to="/reports/$reportId"
                        params={{ reportId: report.id }}
                        className="underline-offset-2 hover:underline"
                      >
                        {report.lesson_title}
                      </Link>
                      <span className="block text-muted-foreground">
                        {formatDateTime(report.lesson_start, i18n.language)}
                      </span>
                    </td>
                    <td className="py-2 pr-4">{report.tutor_name}</td>
                    <td className="py-2 pr-4">{formatDateTime(report.due_at, i18n.language)}</td>
                    <td className="py-2 pr-4">
                      <span
                        className={
                          report.sla_state === "overdue" ? "font-medium text-danger" : undefined
                        }
                      >
                        {t(`delivery.reports.sla.${report.sla_state}`)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.query.hasNextPage ? (
              <Button variant="ghost" size="sm" onClick={() => void list.query.fetchNextPage()}>
                {t("grid.loadMore")}
              </Button>
            ) : null}
          </div>
        )}
      </Tabs>
    </div>
  );
}
