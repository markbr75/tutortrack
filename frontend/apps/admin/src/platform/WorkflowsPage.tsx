import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

type Row = components["schemas"]["PlatformWorkflow"];
type Action = "terminate" | "reset" | "retry";

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
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("workflowConsole.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("workflowConsole.intro")}</p>
      <div className="flex flex-wrap items-end gap-3">
        <SelectField
          label={t("workflowConsole.show")}
          value={state}
          onChange={(e) => setState(e.target.value as typeof state)}
          options={[
            { value: "", label: t("workflowConsole.both") },
            { value: "failed", label: t("workflowConsole.failed") },
            { value: "stuck", label: t("workflowConsole.stuck") },
          ]}
        />
        <TextField
          label={t("workflowConsole.search")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      {rows.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      {rows.data?.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("workflowConsole.none")}</p>
      ) : null}
      <ul className="space-y-3">
        {rows.data?.results.map((row) => (
          <WorkflowCard key={`${row.organisation_id}:${row.workflow_id}`} row={row} />
        ))}
      </ul>
    </div>
  );
}

function WorkflowCard({ row }: { row: Row }) {
  const { t } = useTranslation();
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
    <li className="space-y-2 rounded-lg border border-border p-4 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-medium">
          {row.process} · <span className="font-mono">{row.workflow_id}</span>
        </p>
        <span>{t(`workflowConsole.status.${row.status}`)}</span>
      </div>
      <p className="text-muted-foreground">
        {row.organisation_name} · {t("workflowConsole.started")} {formatDateTime(row.started_at)}
        {row.current_step ? ` · ${row.current_step}` : ""}
      </p>
      {row.last_error ? <p className="text-danger">{row.last_error}</p> : null}
      {row.temporal_url ? (
        <a className="underline" href={row.temporal_url} target="_blank" rel="noreferrer">
          {t("workflowConsole.openTemporal")}
        </a>
      ) : null}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          act.mutate();
        }}
      >
        <SelectField
          label={t("workflowConsole.action")}
          value={action}
          onChange={(e) => setAction(e.target.value as Action)}
          options={actions.map((a) => ({ value: a, label: t(`workflowConsole.actions.${a}`) }))}
        />
        <TextField
          label={t("workflowConsole.reason")}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          required
        />
        <Button type="submit" size="sm" variant="danger" loading={act.isPending}>
          {t("workflowConsole.apply")}
        </Button>
      </form>
      {act.error ? <Alert tone="danger">{act.error.message}</Alert> : null}
    </li>
  );
}
