import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  cn,
  FormPanel,
  figureCell,
  PageHeader,
  PanelRow,
  PanelRows,
  RuledPanel,
  RuledTable,
  SelectField,
  Tabs,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { api, usePermission } from "../api";
import { PanelEmpty, PanelLoading } from "../billing/moneyUi";
import { useIsPhone } from "../billing/useIsPhone";
import { ErrorList } from "../calendar/ErrorList";
import {
  statsOf,
  uploadSpreadsheet,
  useImportCatalogue,
  type ExportJob,
  type ImportBatch,
  type MigrationProject,
  type ReconciliationLine,
  type StepState,
} from "./api";

type TabKey = "imports" | "migrations" | "export";
type Origin = "tutorcruncher" | "tutorbird" | "teachworks" | "csv";
const PRESETS = ["", "tutorbird", "tutorcruncher", "teachworks"] as const;
const STEPS = [
  "people",
  "services",
  "jobs",
  "balances",
  "growth",
  "payment_methods",
  "invite_users",
  "reminders",
] as const;
const STEP_ENTITIES: Record<string, string[]> = {
  people: ["clients", "students", "tutors"],
  services: ["services"],
  jobs: ["jobs", "lessons", "availability"],
  balances: ["opening_balances", "invoices", "payments", "packages", "charges", "payment_requests"],
  growth: ["affiliates", "reviews"],
};
/** Batch states that are failures (danger) or closed (faded ink). */
const FAILED = new Set(["failed"]);
const CLOSED = new Set(["cancelled", "rolled_back"]);
/** The native file button, dressed as a small secondary button. */
const fileInput =
  "block w-full text-sm text-muted-foreground file:mr-3 file:h-9 file:cursor-pointer file:rounded-md file:border file:border-solid file:border-border file:bg-surface file:px-3 file:text-sm file:font-medium file:text-foreground hover:file:bg-muted";

export function DataPage({ initialTab = "imports" }: { initialTab?: TabKey }) {
  const { t } = useTranslation();
  const canExport = usePermission("migration.export.full");
  const canMigrate = usePermission("migration.project.manage");
  const [tab, setTab] = useState<TabKey>(initialTab);
  const tabs = [
    { key: "imports" as const, label: t("dataTransfer.tabs.imports") },
    ...(canMigrate
      ? [{ key: "migrations" as const, label: t("dataTransfer.tabs.migrations") }]
      : []),
    ...(canExport ? [{ key: "export" as const, label: t("dataTransfer.tabs.export") }] : []),
  ];
  return (
    <div>
      <PageHeader title={t("dataTransfer.title")} description={t("dataTransfer.intro")} />
      <Tabs label={t("dataTransfer.title")} tabs={tabs} value={tab} onChange={setTab}>
        {tab === "imports" ? <ImportsTab /> : null}
        {tab === "migrations" ? <MigrationsTab /> : null}
        {tab === "export" ? <ExportTab /> : null}
      </Tabs>
    </div>
  );
}

// --- imports ------------------------------------------------------------------------------------

export function NewImportForm({
  project,
  step,
  entities,
  level,
}: {
  project?: string;
  step?: string;
  entities?: string[];
  level?: 2 | 3;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data: catalogue } = useImportCatalogue();
  const allowed = (catalogue?.entities ?? []).filter(
    (e) => e.allowed && (!entities || entities.includes(e.key)),
  );
  const [entity, setEntity] = useState("");
  const [preset, setPreset] = useState("");
  const [mode, setMode] = useState<"file" | "sheet">("file");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const chosen = entity || allowed[0]?.key || "";
  const create = useMutation({
    mutationFn: async () => {
      if (mode === "sheet") {
        return unwrap(
          await api.POST("/api/v1/imports/google-sheet", {
            body: { url, entity: chosen, sheet: "" },
          }),
        );
      }
      if (!file) throw new Error("no file");
      const fileId = await uploadSpreadsheet(file);
      return unwrap(
        await api.POST("/api/v1/imports", {
          body: {
            file: fileId,
            entity: chosen,
            preset,
            sheet: "",
            project: project ?? null,
            project_step: step ?? "",
          },
        }),
      );
    },
    onSuccess: (batch) =>
      void navigate({ to: "/data/imports/$batchId", params: { batchId: batch.id } }),
  });
  if (!catalogue) {
    return (
      <RuledPanel label={t("dataTransfer.newImport")} flush>
        <PanelLoading label={t("grid.loading")} />
      </RuledPanel>
    );
  }
  if (!allowed.length) {
    return <p className="text-sm text-muted-foreground">{t("dataTransfer.noImportRights")}</p>;
  }
  return (
    <FormPanel
      title={t("dataTransfer.newImport")}
      level={level}
      submit={t("dataTransfer.upload")}
      pending={create.isPending}
      disabled={mode === "file" ? !file : !url}
      onSubmit={() => create.mutate()}
      error={create.error ? <ErrorList error={create.error} /> : null}
      trail={
        create.isPending ? (
          <span role="status" className="text-muted-foreground">
            {t("dataTransfer.uploading")}
          </span>
        ) : null
      }
    >
      <SelectField
        label={t("dataTransfer.entity")}
        value={chosen}
        onChange={(e) => setEntity(e.target.value)}
        options={allowed.map((e) => ({ value: e.key, label: e.label }))}
        hint={allowed.find((e) => e.key === chosen)?.description}
      />
      <SelectField
        label={t("dataTransfer.preset")}
        value={preset}
        onChange={(e) => setPreset(e.target.value)}
        options={PRESETS.map((p) => ({
          value: p,
          label: t(`dataTransfer.presets.${p || "none"}`),
        }))}
      />
      <fieldset className="sm:col-span-2">
        <legend className="mb-1 text-sm font-medium">{t("dataTransfer.from")}</legend>
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={`source-${project ?? ""}${step ?? ""}`}
              checked={mode === "file"}
              onChange={() => setMode("file")}
            />
            {t("dataTransfer.fromFile")}
          </label>
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={`source-${project ?? ""}${step ?? ""}`}
              checked={mode === "sheet"}
              onChange={() => setMode("sheet")}
            />
            {t("dataTransfer.fromSheet")}
          </label>
        </div>
      </fieldset>
      {mode === "file" ? (
        <div className="flex flex-col gap-1 sm:col-span-2">
          <label htmlFor={`import-file-${step ?? ""}`} className="text-sm font-medium">
            {t("dataTransfer.file")}
          </label>
          <input
            id={`import-file-${step ?? ""}`}
            type="file"
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className={fileInput}
          />
          <p className="text-xs">
            <a className="text-link hover:underline" href={`/api/v1/import-templates/${chosen}`} download>
              {t("dataTransfer.template")}
            </a>
          </p>
        </div>
      ) : (
        <div className="sm:col-span-2">
          <TextField
            label={t("dataTransfer.sheetUrl")}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            hint={t("dataTransfer.sheetHint")}
            type="url"
          />
        </div>
      )}
    </FormPanel>
  );
}

/** A batch's status in words: failures in danger, cancelled and rolled back in faded ink. */
export function BatchStatus({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <span
      className={cn(
        FAILED.has(status) && "font-medium text-danger",
        CLOSED.has(status) && "text-muted-foreground",
      )}
    >
      {t(`dataTransfer.status.${status}`)}
    </span>
  );
}

function useEntityName() {
  const { t } = useTranslation();
  return (entity: string): string =>
    t(`dataTransfer.entities.${entity}`, {
      defaultValue: t(`gapG6.entities.${entity}`, { defaultValue: entity }),
    });
}

export function BatchTable({ batches, loading }: { batches: ImportBatch[]; loading?: boolean }) {
  const { t, i18n } = useTranslation();
  const phone = useIsPhone();
  const entityName = useEntityName();
  return (
    <RuledTable
      caption={t("dataTransfer.history")}
      loading={loading}
      loadingLabel={t("grid.loading")}
      empty={!loading && !batches.length ? t("dataTransfer.noImports") : undefined}
      columns={[
        { key: "file", header: t("dataTransfer.columns.file"), width: "min-w-40" },
        ...(phone ? [] : [{ key: "entity", header: t("dataTransfer.columns.entity") }]),
        { key: "status", header: t("dataTransfer.columns.status") },
        { key: "rows", header: t("dataTransfer.columns.rows"), end: true },
        ...(phone ? [] : [{ key: "when", header: t("dataTransfer.columns.when") }]),
      ]}
    >
      {batches.map((b) => (
        <tr key={b.id}>
          <td className="break-words">
            <Link
              to="/data/imports/$batchId"
              params={{ batchId: b.id }}
              className="font-medium hover:underline"
            >
              {b.filename || b.entity}
            </Link>
            {phone ? (
              <span className="block text-xs text-muted-foreground">
                {entityName(b.entity)} · {formatDateTime(b.created_at, i18n.language)}
              </span>
            ) : null}
          </td>
          {phone ? null : <td>{entityName(b.entity)}</td>}
          <td>
            <BatchStatus status={b.status} />
          </td>
          <td className={figureCell}>{statsOf(b).rows ?? 0}</td>
          {phone ? null : (
            <td className="whitespace-nowrap tabular-nums">
              {formatDateTime(b.created_at, i18n.language)}
            </td>
          )}
        </tr>
      ))}
    </RuledTable>
  );
}

function ImportsTab() {
  const { t } = useTranslation();
  const canImport = usePermission("migration.import.manage");
  const { data } = useQuery({
    queryKey: ["imports", "list"],
    queryFn: async () => unwrap(await api.GET("/api/v1/imports")),
  });
  return (
    <div className="space-y-6">
      <RuledPanel title={t("dataTransfer.history")} flush>
        <BatchTable batches={data?.results ?? []} loading={!data} />
      </RuledPanel>
      {canImport ? <NewImportForm /> : null}
    </div>
  );
}

// --- migration projects (cutover assistant) --------------------------------------------------

function NewProjectForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [origin, setOrigin] = useState<Origin>("tutorcruncher");
  const [cutover, setCutover] = useState("");
  const [apiKey, setApiKey] = useState("");
  const needsKey = origin === "tutorcruncher" || origin === "teachworks";
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/migration-projects", {
          body: { name: "", origin, cutover_date: cutover, api_key: needsKey ? apiKey : "" },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["migration-projects"] }),
  });
  return (
    <FormPanel
      title={t("dataTransfer.migration.start")}
      description={t("dataTransfer.migration.intro")}
      submit={t("dataTransfer.migration.begin")}
      pending={create.isPending}
      disabled={!cutover || (needsKey && !apiKey)}
      onSubmit={() => create.mutate()}
      error={create.error ? <ErrorList error={create.error} /> : null}
    >
      <SelectField
        label={t("dataTransfer.migration.origin")}
        value={origin}
        onChange={(e) => setOrigin(e.target.value as Origin)}
        options={["tutorcruncher", "tutorbird", "teachworks", "csv"].map((o) => ({
          value: o,
          label: t(`dataTransfer.sources.${o}`),
        }))}
      />
      <TextField
        label={t("dataTransfer.migration.cutover")}
        type="date"
        required
        value={cutover}
        onChange={(e) => setCutover(e.target.value)}
        hint={t("dataTransfer.migration.cutoverHint")}
      />
      {needsKey ? (
        <TextField
          label={t("dataTransfer.migration.apiKey")}
          type="password"
          autoComplete="off"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
      ) : null}
    </FormPanel>
  );
}

function ProjectView({ project }: { project: MigrationProject }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const steps = (project.steps ?? {}) as Record<string, StepState>;
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["migration-projects"] });
  const path = { params: { path: { id: project.id } } };
  const complete = useMutation({
    mutationFn: async ({ step, skip }: { step: string; skip: boolean }) =>
      unwrap(
        await api.POST("/api/v1/migration-projects/{id}/steps/{step}/complete", {
          params: { path: { id: project.id, step } },
          body: { skip, note: "" },
        }),
      ),
    onSuccess: refresh,
  });
  const invite = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/migration-projects/{id}/invite-tutors", path)),
  });
  const report = (project.reconciliation ?? {}) as { lines?: ReconciliationLine[]; ok?: boolean };
  return (
    <div className="space-y-6">
      <RuledPanel
        title={project.name}
        titleId={`project-${project.id}`}
        description={t("dataTransfer.migration.summary", {
          source: t(`dataTransfer.sources.${project.origin}`),
          date: formatDate(project.cutover_date, i18n.language),
          status: t(`dataTransfer.migration.status.${project.status}`),
        })}
        flush
      >
        <ol className="divide-y divide-rule">
          {STEPS.map((step, index) => {
            const state = steps[step]?.status ?? "pending";
            const current = project.status === "active" && project.current_step === step;
            const batches = project.batches.filter((b) => b.project_step === step);
            return (
              <li
                key={step}
                aria-current={current ? "step" : undefined}
                className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-2 px-5 py-2.5 text-sm"
              >
                <span className="text-muted-foreground tabular-nums">{index + 1}</span>
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <div className="min-w-0">
                      <h3 className={current ? "font-semibold" : "font-medium"}>
                        {t(`dataTransfer.steps.${step}.title`, {
                          defaultValue: t(`gapG6.steps.${step}.title`),
                        })}
                      </h3>
                      <p className="text-xs text-muted-foreground">
                        {t(`dataTransfer.steps.${step}.help`, {
                          defaultValue: t(`gapG6.steps.${step}.help`),
                        })}
                      </p>
                    </div>
                    <span
                      className={cn(
                        state === "pending" || state === "skipped"
                          ? "text-muted-foreground"
                          : undefined,
                        current && "font-semibold",
                      )}
                    >
                      {t(`dataTransfer.stepStatus.${state}`)}
                    </span>
                  </div>
                  {batches.length ? (
                    <div className="rounded-md border border-border">
                      <BatchTable batches={batches} />
                    </div>
                  ) : null}
                  {current ? (
                    <div className="space-y-3 pt-1">
                      {STEP_ENTITIES[step] ? (
                        <NewImportForm
                          project={project.id}
                          step={step}
                          entities={STEP_ENTITIES[step]}
                          level={3}
                        />
                      ) : null}
                      <div className="flex flex-wrap items-center gap-2">
                        {step === "invite_users" ? (
                          <Button size="sm" variant="secondary" onClick={() => invite.mutate()}>
                            {t("dataTransfer.migration.invite")}
                          </Button>
                        ) : null}
                        <Button size="sm" onClick={() => complete.mutate({ step, skip: false })}>
                          {t("dataTransfer.migration.done")}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-muted-foreground"
                          onClick={() => complete.mutate({ step, skip: true })}
                        >
                          {t("dataTransfer.migration.skip")}
                        </Button>
                        {invite.data ? (
                          <span role="status" className="text-success">
                            {t("dataTransfer.migration.invited", { count: invite.data.sent })}
                          </span>
                        ) : null}
                      </div>
                      <ErrorList error={complete.error} />
                    </div>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      </RuledPanel>
      {report.lines?.length ? (
        <RuledPanel
          title={t("dataTransfer.migration.reconciliation")}
          level={3}
          flush
          aside={
            report.ok ? (
              <span className="text-success">{t("dataTransfer.migration.reconciled")}</span>
            ) : null
          }
        >
          {report.ok ? null : (
            <div className="px-5 pt-4">
              <Alert tone="warning">{t("dataTransfer.migration.differences")}</Alert>
            </div>
          )}
          <RuledTable
            caption={t("dataTransfer.migration.reconciliation")}
            columns={[
              { key: "metric", header: t("dataTransfer.migration.metric"), width: "min-w-40" },
              { key: "source", header: t("dataTransfer.migration.source"), end: true, width: "w-32" },
              {
                key: "imported",
                header: t("dataTransfer.migration.imported"),
                end: true,
                width: "w-32",
              },
              {
                key: "difference",
                header: t("dataTransfer.migration.difference"),
                end: true,
                width: "w-32",
              },
            ]}
          >
            {report.lines.map((line) => (
              <tr key={line.metric}>
                <th scope="row" className="py-2.5 font-normal">
                  {t(`dataTransfer.metrics.${line.metric}`, {
                    defaultValue: t(`gapG6.entities.${line.metric}`),
                  })}
                </th>
                <td className={figureCell}>{line.source}</td>
                <td className={figureCell}>{line.imported}</td>
                <td className={cn(figureCell, !line.ok && "font-semibold text-danger")}>
                  {line.difference}
                </td>
              </tr>
            ))}
          </RuledTable>
        </RuledPanel>
      ) : null}
    </div>
  );
}

function MigrationsTab() {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ["migration-projects"],
    queryFn: async () => unwrap(await api.GET("/api/v1/migration-projects")),
    refetchInterval: 5000,
  });
  if (!data) {
    return (
      <RuledPanel label={t("dataTransfer.tabs.migrations")} flush>
        <PanelLoading label={t("grid.loading")} />
      </RuledPanel>
    );
  }
  const active = data.results.filter((p) => p.status === "active");
  return (
    <div className="space-y-6">
      {active.length ? (
        <p className="text-sm text-muted-foreground">{t("dataTransfer.migration.intro")}</p>
      ) : (
        <NewProjectForm />
      )}
      {data.results.map((p) => (
        <ProjectView key={p.id} project={p} />
      ))}
    </div>
  );
}

// --- full export --------------------------------------------------------------------------------

function DownloadExport({ job }: { job: ExportJob }) {
  const { t } = useTranslation();
  const [password, setPassword] = useState("");
  const download = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/data-exports/{id}/download", {
          params: { path: { id: job.id } },
          body: { password },
        }),
      ),
    onSuccess: (link) => window.location.assign(link.url),
  });
  return (
    <form
      className="mt-2 space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        download.mutate();
      }}
    >
      <div className="flex flex-wrap items-start gap-2">
        <div className="w-full sm:w-64">
          <TextField
            size="sm"
            hideLabel
            label={t("dataTransfer.export.password")}
            placeholder={t("dataTransfer.export.password")}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <Button
          type="submit"
          size="sm"
          className="h-9"
          disabled={!password}
          loading={download.isPending}
        >
          {t("dataTransfer.export.download")}
        </Button>
      </div>
      <ErrorList error={download.error} />
    </form>
  );
}

function ExportTab() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["data-exports"],
    queryFn: async () => unwrap(await api.GET("/api/v1/data-exports")),
    refetchInterval: (query) =>
      query.state.data?.results.some((j) => j.status === "requested" || j.status === "running")
        ? 3000
        : false,
  });
  const request = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/data-exports", { body: { reason: "owner" } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["data-exports"] }),
  });
  const jobs = data?.results ?? [];
  return (
    <RuledPanel
      title={t("designS9a.exports")}
      description={t("dataTransfer.export.intro")}
      flush
      footer={
        <Button size="sm" onClick={() => request.mutate()} loading={request.isPending}>
          {t("dataTransfer.export.request")}
        </Button>
      }
    >
      {request.error ? (
        <div className="px-5 pt-4">
          <ErrorList error={request.error} />
        </div>
      ) : null}
      {!data ? (
        <PanelLoading label={t("grid.loading")} />
      ) : jobs.length === 0 ? (
        <PanelEmpty>{t("designS9a.noExports")}</PanelEmpty>
      ) : (
        <PanelRows>
          {jobs.map((job) => (
            <PanelRow key={job.id}>
              <p className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="tabular-nums">{formatDateTime(job.created_at, i18n.language)}</span>
                <span
                  role="status"
                  className={cn(
                    job.status === "failed" && "font-medium text-danger",
                    (job.status === "cancelled" || job.status === "expired") &&
                      "text-muted-foreground",
                    job.status === "ready" && "font-medium",
                  )}
                >
                  {t(`dataTransfer.export.status.${job.status}`)}
                </span>
              </p>
              {job.expires_at && job.status === "ready" ? (
                <p className="text-xs text-muted-foreground">
                  {t("dataTransfer.export.expires", {
                    date: formatDate(job.expires_at, i18n.language),
                  })}
                </p>
              ) : null}
              {job.status === "ready" ? <DownloadExport job={job} /> : null}
            </PanelRow>
          ))}
        </PanelRows>
      )}
    </RuledPanel>
  );
}
