import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, RuledTable, SelectField, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";

import { api, usePermission } from "../api";
import { useIsPhone } from "../billing/useIsPhone";
import { eventLabel, useSchemas, type Schema } from "./common";

type Run = components["schemas"]["AutomationRun"];
type RunStep = components["schemas"]["RunStep"];
type Translate = (key: string, options?: Record<string, unknown>) => string;

const UNDER_WAY = ["running", "waiting", "paused"];
const CANCELLED = "cancelled"; // the stop reason of a run staff cancelled

/** Where a run is, in words: "Waiting until 12 Nov, 09:00", "Stopped: Invoice paid". */
function runPlace(run: Run, schema: Schema | undefined, t: Translate, lang: string) {
  const when = (iso: string) => formatDateTime(iso, lang);
  switch (run.status) {
    case "waiting":
      return run.waiting_until
        ? t("workflows.runs.waitingUntil", { when: when(run.waiting_until) })
        : t("automations.runStatus.waiting");
    case "running":
      return t("workflows.runs.running", { count: run.steps_done });
    case "paused":
      return t("workflows.runs.held");
    case "stopped":
      if (run.stop_reason === CANCELLED) return t("workflows.runs.cancelled");
      return run.stop_reason && schema
        ? t("workflows.runs.stoppedBy", { event: eventLabel(schema, run.stop_reason) })
        : t("automations.runStatus.stopped");
    case "completed":
      return run.finished_at
        ? t("workflows.runs.finished", { when: when(run.finished_at) })
        : t("automations.runStatus.completed");
    default:
      return t(`automations.runStatus.${run.status ?? "running"}`);
  }
}

/** "Step 3", or "Yes: step 1" on a split's path (keys count the engine's steps). */
function stepName(key: string, t: Translate) {
  const parts = key.split(".");
  const n = Number(parts[parts.length - 1]) + 1;
  if (parts.length === 1) return t("workflows.step", { n });
  const path = parts[1] === "then" ? t("workflows.yes") : t("workflows.no");
  return t("workflows.pathStep", { path, n });
}

function stepText(step: RunStep, t: Translate, lang: string) {
  const result = (step.result ?? {}) as Record<string, unknown>;
  if (step.step_type === "wait") {
    if (!step.resume_at) return t(`workflows.runs.step.${step.status}`);
    const key = step.status === "waiting" ? "waitingUntil" : "waitedUntil";
    return t(`workflows.runs.${key}`, { when: formatDateTime(step.resume_at, lang) });
  }
  if (step.step_type === "branch") {
    return t("workflows.runs.answer", {
      answer: result.matched ? t("workflows.yes") : t("workflows.no"),
    });
  }
  if (step.status === "skipped") {
    return typeof result.skipped === "string" && result.skipped !== "only_if"
      ? t("workflows.runs.skippedBecause", { reason: result.skipped })
      : t("workflows.runs.skippedOnlyIf");
  }
  if (step.status === "failed") return step.error || t("automations.runStatus.failed");
  return t(`workflows.runs.step.${step.status}`);
}

/** The steps a run has done so far (its log). */
function RunSteps({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const detail = useQuery({
    queryKey: ["workflow-run", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/workflow-runs/{id}", { params: { path: { id } } })),
  });
  if (!detail.data) return <Spinner label={t("grid.loading")} />;
  if (detail.data.steps.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("workflows.runs.noSteps")}</p>;
  }
  return (
    <ol className="space-y-1 text-sm" aria-label={t("workflows.runs.stepsSoFar")}>
      {detail.data.steps.map((step) => (
        <li key={step.step_key} className="flex flex-wrap gap-x-2">
          <span className="font-medium">{stepName(step.step_key, t)}</span>
          <span className={step.status === "failed" ? "text-danger" : "text-muted-foreground"}>
            {stepText(step, t, i18n.language)}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function RunRows({ runs, bare = false }: { runs: Run[]; bare?: boolean }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { schema } = useSchemas();
  const phone = useIsPhone();
  const custom = usePermission("automation.manage");
  const builtin = usePermission("automation.builtin.manage");
  const [open, setOpen] = useState<string | null>(null);
  const done = () => {
    void queryClient.invalidateQueries({ queryKey: ["workflow-runs"] });
    void queryClient.invalidateQueries({ queryKey: ["workflow-run"] });
  };
  const retry = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/workflow-runs/{id}/retry", { params: { path: { id } } })),
    onSuccess: done,
  });
  const cancel = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/workflow-runs/{id}/cancel", { params: { path: { id } } })),
    // The run ends within moments, once its workflow hears; look again shortly.
    onSuccess: () => {
      done();
      window.setTimeout(done, 1500);
    },
  });
  const canChange = (r: Run) => (r.automation_kind === "builtin" ? builtin : custom);
  const record = (r: Run) =>
    r.record_label ||
    [
      schema?.record_types.find((x) => x.key === r.subject_type)?.label ?? r.subject_type,
      (r.subject_id ?? "").slice(0, 8),
    ]
      .filter(Boolean)
      .join(" ");
  const started = (r: Run) => formatDateTime(r.started_at, i18n.language);
  const columns = phone ? 3 : 5;
  const error = retry.error ?? cancel.error;
  return (
    <div>
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
      <RuledTable
        framed={!bare}
        caption={t("workflows.tabs.runs")}
        empty={runs.length === 0 ? t("automations.noRuns") : undefined}
        columns={[
          { header: t("workflows.workflow") },
          ...(phone
            ? []
            : [{ header: t("automations.record") }, { header: t("automations.started") }]),
          { header: t("workflows.runs.where") },
          { header: t("automations.actions"), hidden: true },
        ]}
      >
        {runs.map((r) => (
          <Fragment key={r.id}>
            <tr>
              <td>
                <span className="font-medium">{r.automation_name}</span>
                <span className="block text-xs text-muted-foreground tabular-nums">
                  {phone
                    ? [record(r), started(r)].join(" · ")
                    : t("automations.version", { n: r.version })}
                </span>
              </td>
              {phone ? null : (
                <>
                  <td>{record(r)}</td>
                  <td className="whitespace-nowrap tabular-nums">{started(r)}</td>
                </>
              )}
              <td>
                <span className={r.status === "failed" ? "font-medium text-danger" : undefined}>
                  {runPlace(r, schema, t, i18n.language)}
                </span>
                {r.error ? <span className="block text-xs text-danger">{r.error}</span> : null}
              </td>
              <td className="text-right">
                <div className="flex flex-wrap justify-end gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-expanded={open === r.id}
                    aria-controls={`run-steps-${r.id}`}
                    aria-label={t("workflows.runs.showSteps", { name: r.automation_name })}
                    onClick={() => setOpen(open === r.id ? null : r.id)}
                  >
                    {t("workflows.runs.steps")}
                  </Button>
                  {canChange(r) && UNDER_WAY.includes(r.status ?? "") ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={cancel.isPending && cancel.variables === r.id}
                      onClick={() => {
                        if (
                          window.confirm(t("workflows.runs.confirmCancel", { record: record(r) }))
                        )
                          cancel.mutate(r.id);
                      }}
                    >
                      {t("workflows.runs.cancel")}
                    </Button>
                  ) : null}
                  {canChange(r) && r.status === "failed" ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={retry.isPending && retry.variables === r.id}
                      onClick={() => retry.mutate(r.id)}
                    >
                      {t("automations.retry")}
                    </Button>
                  ) : null}
                </div>
              </td>
            </tr>
            {open === r.id ? (
              <tr id={`run-steps-${r.id}`}>
                <td colSpan={columns} className="bg-muted">
                  <RunSteps id={r.id} />
                </td>
              </tr>
            ) : null}
          </Fragment>
        ))}
      </RuledTable>
    </div>
  );
}

type Filter = "" | "under_way" | "failed";

/** The Runs tab: every workflow's runs, newest first, filtered by where they are. */
export function RunList() {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<Filter>("");
  const runs = useQuery({
    queryKey: ["workflow-runs", "all", filter],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/workflow-runs", {
          params: { query: filter ? { status: filter } : {} },
        }),
      ),
  });
  return (
    <div className="space-y-4">
      <div className="max-w-xs">
        <SelectField
          label={t("workflows.runs.show")}
          value={filter}
          onChange={(e) => setFilter(e.target.value as Filter)}
          options={[
            { value: "", label: t("workflows.runs.filter.all") },
            { value: "under_way", label: t("workflows.runs.filter.underWay") },
            { value: "failed", label: t("workflows.runs.filter.failed") },
          ]}
        />
      </div>
      {runs.data ? <RunRows runs={runs.data.results} /> : <Spinner label={t("grid.loading")} />}
    </div>
  );
}
