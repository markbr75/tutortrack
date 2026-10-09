import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { ErrorFallback, Spinner } from "@tutortrack/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { TaskList } from "./Activity";

/** "My tasks" with an overdue filter (FR-05-8). */
export function TasksPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [overdueOnly, setOverdueOnly] = useState(false);
  const query = { mine: true, status: "open" as const, ...(overdueOnly ? { overdue: true } : {}) };
  const tasks = useQuery({
    queryKey: ["tasks", "mine", query],
    queryFn: async () => unwrap(await api.GET("/api/v1/tasks", { params: { query } })),
  });
  return (
    <section className="max-w-3xl">
      <h1 className="mb-4 text-2xl font-semibold">{t("crm.task.mine")}</h1>
      <label className="mb-4 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4"
          checked={overdueOnly}
          onChange={(e) => setOverdueOnly(e.target.checked)}
        />
        {t("crm.task.overdueOnly")}
      </label>
      {tasks.isError ? (
        <ErrorFallback
          title={t("errors.generic")}
          retryLabel={t("errors.retry")}
          onRetry={() => void tasks.refetch()}
        />
      ) : tasks.isPending ? (
        <Spinner label={t("grid.loading")} />
      ) : tasks.data.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("crm.task.allDone")}</p>
      ) : (
        <TaskList
          tasks={tasks.data.results}
          onChanged={() => void queryClient.invalidateQueries({ queryKey: ["tasks"] })}
        />
      )}
    </section>
  );
}
