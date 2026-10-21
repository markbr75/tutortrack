import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { ErrorFallback, PageHeader, Spinner } from "@tutortrack/ui";
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
      <PageHeader title={t("crm.task.mine")} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="flex h-9 items-center gap-2 px-1 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={overdueOnly}
            onChange={(e) => setOverdueOnly(e.target.checked)}
          />
          {t("crm.task.overdueOnly")}
        </label>
      </div>
      {tasks.isError ? (
        <ErrorFallback
          title={t("errors.generic")}
          retryLabel={t("errors.retry")}
          onRetry={() => void tasks.refetch()}
        />
      ) : (
        <div className="rounded-xl border border-border bg-surface px-5">
          {tasks.isPending ? (
            <div className="py-3">
              <Spinner className="sr-only" label={t("grid.loading")} />
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  aria-hidden="true"
                  className="my-2 h-8 animate-pulse rounded bg-muted"
                />
              ))}
            </div>
          ) : tasks.data.results.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              {t("crm.task.allDone")}
            </p>
          ) : (
            <TaskList
              tasks={tasks.data.results}
              onChanged={() => void queryClient.invalidateQueries({ queryKey: ["tasks"] })}
            />
          )}
        </div>
      )}
    </section>
  );
}
