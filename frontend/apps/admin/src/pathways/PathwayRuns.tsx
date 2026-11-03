import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Panel, PanelRow, PanelRows, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api, usePermission } from "../api";

type Run = components["schemas"]["PathwayRun"];
type RunStep = components["schemas"]["PathwayStep"];
type Act = "complete" | "skip" | "reject" | "remind";
type Translate = (key: string, options?: Record<string, unknown>) => string;

const CLOSED = ["done", "skipped", "rejected"];

function runLine(run: Run, t: Translate, lang: string): string {
  const progress = t("pathways.runs.progress", {
    done: run.progress.finished ?? 0,
    total: run.progress.total ?? 0,
  });
  const stage = run.stages.find((s) => s.key === run.stage);
  const where =
    run.status === "running"
      ? stage
        ? t("pathways.runs.atStage", { stage: stage.name })
        : t("pathways.runStatus.running")
      : `${t(`pathways.runStatus.${run.status}`)}${
          run.finished_at ? ` ${formatDate(run.finished_at, lang)}` : ""
        }`;
  return [where, progress].join(" · ");
}

/** The pathways a job's tutors (or one tutor) follow, as timelines staff act on (FR-34-1). */
export function PathwayRunsPanel({
  jobId,
  tutorId,
  tutors,
  footer,
}: {
  jobId?: string;
  tutorId?: string;
  /** The tutors a pathway can be started for (on a job page). */
  tutors?: { id: string; name: string }[];
  footer?: ReactNode;
}) {
  const { t, i18n } = useTranslation();
  const canView = usePermission("pathway.view");
  const [open, setOpen] = useState<string | null>(null);
  const query = jobId ? { record_type: "job", record_id: jobId } : { tutor: tutorId };
  const runs = useQuery({
    queryKey: ["pathway-runs", query],
    enabled: canView,
    queryFn: async () => unwrap(await api.GET("/api/v1/pathway-runs", { params: { query } })),
  });
  if (!canView) return null;
  const rows = runs.data?.results ?? [];
  return (
    <Panel title={t("pathways.runs.title")} flush>
      {runs.data && !rows.length ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">{t("pathways.runs.none")}</p>
      ) : null}
      <PanelRows>
        {rows.map((run) => (
          <PanelRow key={run.id}>
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
              <div className="min-w-0">
                <p className="font-medium">
                  {run.template_name}
                  {jobId && run.tutor ? (
                    <span className="font-normal text-muted-foreground"> · {run.tutor.name}</span>
                  ) : null}
                </p>
                <p className="text-xs text-muted-foreground tabular-nums">
                  {runLine(run, t, i18n.language)}
                </p>
              </div>
              <Button
                size="sm"
                variant="secondary"
                aria-expanded={open === run.id}
                aria-label={t("pathways.runs.showSteps", { name: run.template_name })}
                onClick={() => setOpen(open === run.id ? null : run.id)}
              >
                {open === run.id ? t("pathways.runs.hide") : t("pathways.runs.steps")}
              </Button>
            </div>
            {open === run.id ? <RunTimeline runId={run.id} /> : null}
          </PanelRow>
        ))}
      </PanelRows>
      {jobId && tutors?.length ? <StartPathway jobId={jobId} tutors={tutors} /> : null}
      {footer}
    </Panel>
  );
}

function RunTimeline({ runId }: { runId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canAct = usePermission("pathway.step.complete");
  const canManage = usePermission("pathway.run.manage");
  const [asking, setAsking] = useState<{ key: string; act: Act } | null>(null);
  const [reason, setReason] = useState("");
  const detail = useQuery({
    queryKey: ["pathway-run", runId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/pathway-runs/{id}", { params: { path: { id: runId } } })),
  });
  const refresh = () => {
    setAsking(null);
    setReason("");
    void queryClient.invalidateQueries({ queryKey: ["pathway-run", runId] });
    void queryClient.invalidateQueries({ queryKey: ["pathway-runs"] });
  };
  const act = useMutation({
    mutationFn: async ({ key, act, why }: { key: string; act: Act; why?: string }) =>
      unwrap(
        await api.POST("/api/v1/pathway-runs/{id}/steps/{key}/{act}", {
          params: { path: { id: runId, key, act } },
          body: act === "skip" || act === "reject" ? { reason: why ?? "" } : {},
        }),
      ),
    onSuccess: refresh,
  });
  const cancel = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/pathway-runs/{id}/cancel", {
          params: { path: { id: runId } },
          body: { reason: "" },
        }),
      ),
    onSuccess: refresh,
  });
  if (!detail.data) return null;
  const run = detail.data;
  const running = run.status === "running";
  const actions = (step: RunStep) => {
    if (!running || !canAct || CLOSED.includes(step.status ?? "")) return null;
    const buttons: { act: Act; label: string; asks?: boolean }[] = [];
    if (step.status === "review") {
      buttons.push({ act: "complete", label: t("pathways.runs.accept") });
      buttons.push({ act: "reject", label: t("pathways.runs.sendBack"), asks: true });
    } else if (step.status === "open" && step.assignee === "staff") {
      buttons.push({
        act: "complete",
        label:
          step.step_type === "staff_review" ? t("pathways.runs.approve") : t("pathways.runs.done"),
      });
      if (step.step_type === "staff_review") {
        buttons.push({ act: "reject", label: t("pathways.runs.turnDown"), asks: true });
      }
    }
    if (step.status === "open" && ["participant", "staff"].includes(step.assignee ?? "")) {
      buttons.push({ act: "remind", label: t("pathways.runs.remind") });
    }
    buttons.push({ act: "skip", label: t("pathways.runs.skip"), asks: true });
    return (
      <span className="flex flex-wrap gap-2">
        {buttons.map((b) => (
          <Button
            key={b.act}
            size="sm"
            variant={b.act === "complete" ? "primary" : b.act === "skip" ? "ghost" : "secondary"}
            aria-label={`${b.label}: ${step.name}`}
            disabled={act.isPending}
            onClick={() =>
              b.asks
                ? setAsking({ key: step.key, act: b.act })
                : act.mutate({ key: step.key, act: b.act })
            }
          >
            {b.label}
          </Button>
        ))}
      </span>
    );
  };
  return (
    <div className="mt-3 border-t border-rule pt-3">
      {run.stages.map((stage) => (
        <section key={stage.key} className="mb-3" aria-label={stage.name}>
          <h4 className="text-xs font-semibold text-muted-foreground">
            {stage.name}
            {stage.gate
              ? ` · ${t(run.gates.includes(stage.gate) ? "pathways.runs.gateReached" : "pathways.runs.gate", { gate: stage.gate })}`
              : ""}
          </h4>
          <ol className="mt-1 divide-y divide-rule">
            {run.steps
              .filter((s) => s.stage === stage.key)
              .map((step) => (
                <li key={step.id} className="py-2">
                  <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                    <div className="min-w-0">
                      <p>{step.name}</p>
                      <p className="text-xs text-muted-foreground tabular-nums">
                        {[
                          t(`pathways.assignee.${step.assignee}`),
                          t(`pathways.stepStatus.${step.status}`),
                          step.due_at && !CLOSED.includes(step.status ?? "")
                            ? t("pathways.runs.due", {
                                when: formatDateTime(step.due_at, i18n.language),
                              })
                            : null,
                          step.completed_by,
                          step.reason || null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    </div>
                    {actions(step)}
                  </div>
                  {asking?.key === step.key ? (
                    <form
                      className="mt-2 flex flex-wrap items-end gap-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        act.mutate({ key: step.key, act: asking.act, why: reason });
                      }}
                    >
                      <TextField
                        size="sm"
                        autoFocus
                        label={t("pathways.runs.why")}
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Escape") setAsking(null);
                        }}
                      />
                      <Button size="sm" type="submit" disabled={!reason.trim() || act.isPending}>
                        {t("pathways.runs.confirm")}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        type="button"
                        onClick={() => setAsking(null)}
                      >
                        {t("common.cancel")}
                      </Button>
                    </form>
                  ) : null}
                </li>
              ))}
          </ol>
        </section>
      ))}
      {act.error ? <Alert tone="danger">{act.error.message}</Alert> : null}
      {running && canManage ? (
        <Button
          size="sm"
          variant="ghost"
          className="text-muted-foreground hover:text-foreground"
          disabled={cancel.isPending}
          onClick={() => cancel.mutate()}
        >
          {t("pathways.runs.cancel")}
        </Button>
      ) : null}
    </div>
  );
}

function StartPathway({
  jobId,
  tutors,
}: {
  jobId: string;
  tutors: { id: string; name: string }[];
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canStart = usePermission("pathway.run.manage");
  const [template, setTemplate] = useState("");
  const [tutor, setTutor] = useState(tutors[0]?.id ?? "");
  const templates = useQuery({
    queryKey: ["pathway-templates"],
    enabled: canStart,
    queryFn: async () => unwrap(await api.GET("/api/v1/pathway-templates")),
  });
  const start = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/pathway-runs", {
          body: { template, tutor, record_id: jobId },
        }),
      ),
    onSuccess: () => {
      setTemplate("");
      void queryClient.invalidateQueries({ queryKey: ["pathway-runs"] });
    },
  });
  if (!canStart) return null;
  const options = (templates.data ?? []).filter((p) => p.active && p.record_type === "job");
  return (
    <form
      className="flex flex-wrap items-end gap-2 border-t border-rule px-5 py-3"
      aria-label={t("pathways.runs.start")}
      onSubmit={(e) => {
        e.preventDefault();
        start.mutate();
      }}
    >
      <SelectField
        size="sm"
        label={t("pathways.runs.pathway")}
        value={template}
        options={[
          { value: "", label: t("pathways.runs.choosePathway") },
          ...options.map((p) => ({ value: p.id, label: p.name })),
        ]}
        onChange={(e) => setTemplate(e.target.value)}
      />
      {tutors.length > 1 ? (
        <SelectField
          size="sm"
          label={t("pathways.runs.tutor")}
          value={tutor}
          options={tutors.map((x) => ({ value: x.id, label: x.name }))}
          onChange={(e) => setTutor(e.target.value)}
        />
      ) : null}
      <Button size="sm" variant="secondary" type="submit" disabled={!template || start.isPending}>
        {t("pathways.runs.start")}
      </Button>
      {start.error ? <Alert tone="danger">{start.error.message}</Alert> : null}
    </form>
  );
}

/** Which Join pathway tutors put on this job follow (FR-34-2); empty: the business default. */
export function JoinPathwayChoice({ jobId, value }: { jobId: string; value: string | null }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canEdit = usePermission("jobs.job.edit");
  const templates = useQuery({
    queryKey: ["pathway-templates"],
    enabled: canEdit,
    queryFn: async () => unwrap(await api.GET("/api/v1/pathway-templates")),
  });
  const save = useMutation({
    mutationFn: async (join_template: string | null) =>
      unwrap(
        await api.PATCH("/api/v1/jobs/{id}", {
          params: { path: { id: jobId } },
          body: { join_template },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
  });
  const joins = (templates.data ?? []).filter((p) => p.kind === "join" && p.active);
  if (!canEdit || !joins.length) return null;
  return (
    <div className="flex flex-wrap items-end gap-2 border-t border-rule px-5 py-3">
      <SelectField
        size="sm"
        label={t("pathways.runs.joinForJob")}
        value={value ?? ""}
        disabled={save.isPending}
        options={[
          { value: "", label: t("pathways.runs.useDefault") },
          ...joins.map((p) => ({ value: p.id, label: p.name })),
        ]}
        onChange={(e) => save.mutate(e.target.value || null)}
      />
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
    </div>
  );
}
