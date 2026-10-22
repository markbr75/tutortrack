import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PageHeader,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

type Row = components["schemas"]["PlatformWorkflow"];
type Action = "terminate" | "reset" | "retry";

/** Failures in danger; a run that has stopped moving waits on us (margin red). */
const STATUS_CLASS: Record<string, string> = {
  failed: "font-medium text-danger",
  timed_out: "font-medium text-danger",
  terminated: "font-medium text-danger",
  running: "font-semibold text-margin",
  completed: "text-muted-foreground",
  cancelled: "text-muted-foreground",
};

/** G6 (FR-32-10): failed and stuck durable processes across organisations, with
 *  terminate, reset and retry (a reason is required) and links to the Temporal UI. */
export function WorkflowsPage() {
  const { t } = useTranslation();
  const [state, setState] = useState<"" | "failed" | "stuck">("");
  const [search, setSearch] = useState("");
  const rows = useQuery({
    queryKey: ["platform", "workflows", state, search],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/platform/workflows", {
          params: { query: { state: state || undefined, search: search || undefined } },
        }),
      ),
  });
  const list = rows.data?.results ?? [];
  return (
    <div className="max-w-5xl">
      <PageHeader title={t("workflowConsole.title")} description={t("workflowConsole.intro")} />
      <form
        role="search"
        aria-label={t("workflowConsole.title")}
        className="mb-4 flex flex-wrap items-center gap-2"
        onSubmit={(e) => e.preventDefault()}
      >
        <div className="min-w-56 flex-1">
          <TextField
            type="search"
            label={t("workflowConsole.search")}
            hideLabel
            size="sm"
            placeholder={t("workflowConsole.search")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <SelectField
          label={t("workflowConsole.show")}
          hideLabel
          size="sm"
          value={state}
          onChange={(e) => setState(e.target.value as typeof state)}
          options={[
            { value: "", label: t("workflowConsole.both") },
            { value: "failed", label: t("workflowConsole.failed") },
            { value: "stuck", label: t("workflowConsole.stuck") },
          ]}
        />
      </form>
      <RuledPanel label={t("workflowConsole.title")} rule={list.length ? "margin" : "border"} flush>
        {rows.isPending ? (
          <div className="px-5 py-4">
            <Spinner label={t("grid.loading")} />
          </div>
        ) : list.length === 0 ? (
          <p className="px-5 py-6 text-sm text-muted-foreground">{t("workflowConsole.none")}</p>
        ) : (
          <ul className="divide-y divide-rule">
            {list.map((row) => (
              <WorkflowRow key={`${row.organisation_id}:${row.workflow_id}`} row={row} />
            ))}
          </ul>
        )}
      </RuledPanel>
    </div>
  );
}

/** One process: what it is and where it stopped, then the action with its reason. */
function WorkflowRow({ row }: { row: Row }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [action, setAction] = useState<Action>(row.status === "running" ? "terminate" : "retry");
  const [reason, setReason] = useState("");
  const act = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/platform/workflows/{organisation_id}/{workflow_id}", {
          params: { path: { organisation_id: row.organisation_id, workflow_id: row.workflow_id } },
          body: { action, reason },
        }),
      ),
    onSuccess: () => {
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["platform", "workflows"] });
    },
  });
  const actions: Action[] = row.status === "running" ? ["terminate", "reset"] : ["retry"];
  return (
    <li className="space-y-2 px-5 py-3 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="min-w-0 font-medium">
          {row.process}{" "}
          <span className="font-mono text-xs font-normal break-all text-muted-foreground">
            {row.workflow_id}
          </span>
        </p>
        <span className={STATUS_CLASS[row.status] ?? ""}>
          {t(`workflowConsole.status.${row.status}`)}
        </span>
      </div>
      <p className="text-xs text-muted-foreground tabular-nums">
        {row.organisation_name} · {t("workflowConsole.started")}{" "}
        {formatDateTime(row.started_at, i18n.language)}
        {row.current_step ? ` · ${row.current_step}` : ""}
        {row.temporal_url ? (
          <>
            {" · "}
            <a
              className="font-medium text-link underline-offset-2 hover:underline"
              href={row.temporal_url}
              target="_blank"
              rel="noreferrer"
            >
              {t("workflowConsole.openTemporal")}
            </a>
          </>
        ) : null}
      </p>
      {row.last_error ? <p className="text-xs break-words text-danger">{row.last_error}</p> : null}
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          act.mutate();
        }}
      >
        <SelectField
          label={t("workflowConsole.action")}
          hideLabel
          size="sm"
          value={action}
          onChange={(e) => setAction(e.target.value as Action)}
          options={actions.map((a) => ({ value: a, label: t(`workflowConsole.actions.${a}`) }))}
        />
        <div className="min-w-48 flex-1 sm:max-w-sm">
          <TextField
            label={t("workflowConsole.reason")}
            hideLabel
            size="sm"
            placeholder={t("workflowConsole.reason")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            required
          />
        </div>
        <Button type="submit" size="sm" variant="danger" className="h-9" loading={act.isPending}>
          {t("workflowConsole.apply")}
        </Button>
      </form>
      {act.error ? <Alert tone="danger">{act.error.message}</Alert> : null}
    </li>
  );
}
