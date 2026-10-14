import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { api, usePermission } from "../api";
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
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">{t("dataTransfer.title")}</h1>
        <p className="text-muted-foreground">{t("dataTransfer.intro")}</p>
      </header>
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
}: {
  project?: string;
  step?: string;
  entities?: string[];
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
  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };
  if (!catalogue) return <Spinner />;
  if (!allowed.length) return <p>{t("dataTransfer.noImportRights")}</p>;
  return (
    <form onSubmit={submit} className="space-y-3 rounded-md border border-border p-4">
      <h2 className="text-lg font-semibold">{t("dataTransfer.newImport")}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
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
      </div>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">{t("dataTransfer.from")}</legend>
        <label className="mr-4 inline-flex items-center gap-2 text-sm">
          <input
            type="radio"
            name="source"
            checked={mode === "file"}
            onChange={() => setMode("file")}
          />
          {t("dataTransfer.fromFile")}
        </label>
        <label className="inline-flex items-center gap-2 text-sm">
          <input
            type="radio"
            name="source"
            checked={mode === "sheet"}
            onChange={() => setMode("sheet")}
          />
          {t("dataTransfer.fromSheet")}
        </label>
      </fieldset>
      {mode === "file" ? (
        <div className="space-y-1">
          <label htmlFor="import-file" className="block text-sm font-medium">
            {t("dataTransfer.file")}
          </label>
          <input
            id="import-file"
            type="file"
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block text-sm"
          />
          <p className="text-sm text-muted-foreground">
            <a className="underline" href={`/api/v1/import-templates/${chosen}`} download>
              {t("dataTransfer.template")}
            </a>
          </p>
        </div>
      ) : (
        <TextField
          label={t("dataTransfer.sheetUrl")}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          hint={t("dataTransfer.sheetHint")}
          type="url"
        />
      )}
      <Button
        type="submit"
        disabled={create.isPending || (mode === "file" ? !file : !url)}
        aria-busy={create.isPending}
      >
        {create.isPending ? t("dataTransfer.uploading") : t("dataTransfer.upload")}
      </Button>
      <ErrorList error={create.error} />
    </form>
  );
}

export function BatchTable({ batches }: { batches: ImportBatch[] }) {
  const { t, i18n } = useTranslation();
  if (!batches.length)
    return <p className="text-muted-foreground">{t("dataTransfer.noImports")}</p>;
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">{t("dataTransfer.history")}</caption>
      <thead>
        <tr className="text-left">
          <th scope="col">{t("dataTransfer.columns.file")}</th>
          <th scope="col">{t("dataTransfer.columns.entity")}</th>
          <th scope="col">{t("dataTransfer.columns.status")}</th>
          <th scope="col">{t("dataTransfer.columns.rows")}</th>
          <th scope="col">{t("dataTransfer.columns.when")}</th>
        </tr>
      </thead>
      <tbody>
        {batches.map((b) => (
          <tr key={b.id} className="border-t border-border">
            <td>
              <Link to="/data/imports/$batchId" params={{ batchId: b.id }} className="underline">
                {b.filename || b.entity}
              </Link>
            </td>
            <td>
              {t(`dataTransfer.entities.${b.entity}`, {
                defaultValue: t(`gapG6.entities.${b.entity}`, { defaultValue: b.entity }),
              })}
            </td>
            <td>{t(`dataTransfer.status.${b.status}`)}</td>
            <td>{statsOf(b).rows ?? 0}</td>
            <td>{formatDateTime(b.created_at, i18n.language)}</td>
          </tr>
        ))}
      </tbody>
    </table>
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
      {canImport ? <NewImportForm /> : null}
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">{t("dataTransfer.history")}</h2>
        {data ? <BatchTable batches={data.results} /> : <Spinner />}
      </section>
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
    <form
      className="space-y-3 rounded-md border border-border p-4"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <h2 className="text-lg font-semibold">{t("dataTransfer.migration.start")}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
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
      </div>
      <Button type="submit" disabled={!cutover || (needsKey && !apiKey) || create.isPending}>
        {t("dataTransfer.migration.begin")}
      </Button>
      <ErrorList error={create.error} />
    </form>
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
    <section
      className="space-y-4 rounded-md border border-border p-4"
      aria-labelledby={`project-${project.id}`}
    >
      <h2 id={`project-${project.id}`} className="text-lg font-semibold">
        {project.name}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t("dataTransfer.migration.summary", {
          source: t(`dataTransfer.sources.${project.origin}`),
          date: formatDate(project.cutover_date, i18n.language),
          status: t(`dataTransfer.migration.status.${project.status}`),
        })}
      </p>
      <ol className="space-y-3">
        {STEPS.map((step, index) => {
          const state = steps[step]?.status ?? "pending";
          const current = project.status === "active" && project.current_step === step;
          const batches = project.batches.filter((b) => b.project_step === step);
          return (
            <li
              key={step}
              aria-current={current ? "step" : undefined}
              className="rounded-md border border-border p-3 aria-[current=step]:border-primary"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-medium">
                  {index + 1}.{" "}
                  {t(`dataTransfer.steps.${step}.title`, {
                    defaultValue: t(`gapG6.steps.${step}.title`),
                  })}
                </h3>
                <span className="text-sm">{t(`dataTransfer.stepStatus.${state}`)}</span>
              </div>
              <p className="text-sm text-muted-foreground">
                {t(`dataTransfer.steps.${step}.help`, {
                  defaultValue: t(`gapG6.steps.${step}.help`),
                })}
              </p>
              {batches.length ? <BatchTable batches={batches} /> : null}
              {current ? (
                <div className="mt-2 space-y-2">
                  {STEP_ENTITIES[step] ? (
                    <NewImportForm
                      project={project.id}
                      step={step}
                      entities={STEP_ENTITIES[step]}
                    />
                  ) : null}
                  {step === "invite_users" ? (
                    <div className="space-y-1">
                      <Button variant="secondary" onClick={() => invite.mutate()}>
                        {t("dataTransfer.migration.invite")}
                      </Button>
                      {invite.data ? (
                        <p role="status">
                          {t("dataTransfer.migration.invited", { count: invite.data.sent })}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                  <div className="flex flex-wrap gap-2">
                    <Button onClick={() => complete.mutate({ step, skip: false })}>
                      {t("dataTransfer.migration.done")}
                    </Button>
                    <Button variant="ghost" onClick={() => complete.mutate({ step, skip: true })}>
                      {t("dataTransfer.migration.skip")}
                    </Button>
                  </div>
                  <ErrorList error={complete.error} />
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
      {report.lines?.length ? (
        <div className="space-y-2">
          <h3 className="font-medium">{t("dataTransfer.migration.reconciliation")}</h3>
          {report.ok ? (
            <Alert tone="success">{t("dataTransfer.migration.reconciled")}</Alert>
          ) : (
            <Alert tone="warning">{t("dataTransfer.migration.differences")}</Alert>
          )}
          <table className="w-full text-sm">
            <caption className="sr-only">{t("dataTransfer.migration.reconciliation")}</caption>
            <thead>
              <tr className="text-left">
                <th scope="col">{t("dataTransfer.migration.metric")}</th>
                <th scope="col">{t("dataTransfer.migration.source")}</th>
                <th scope="col">{t("dataTransfer.migration.imported")}</th>
                <th scope="col">{t("dataTransfer.migration.difference")}</th>
              </tr>
            </thead>
            <tbody>
              {report.lines.map((line) => (
                <tr key={line.metric} className="border-t border-border">
                  <th scope="row" className="font-normal">
                    {t(`dataTransfer.metrics.${line.metric}`, {
                      defaultValue: t(`gapG6.entities.${line.metric}`),
                    })}
                  </th>
                  <td>{line.source}</td>
                  <td>{line.imported}</td>
                  <td className={line.ok ? "" : "font-semibold text-danger"}>{line.difference}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function MigrationsTab() {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ["migration-projects"],
    queryFn: async () => unwrap(await api.GET("/api/v1/migration-projects")),
    refetchInterval: 5000,
  });
  if (!data) return <Spinner />;
  const active = data.results.filter((p) => p.status === "active");
  return (
    <div className="space-y-6">
      <p>{t("dataTransfer.migration.intro")}</p>
      {active.length ? null : <NewProjectForm />}
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
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        download.mutate();
      }}
    >
      <TextField
        label={t("dataTransfer.export.password")}
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <Button type="submit" disabled={!password || download.isPending}>
        {t("dataTransfer.export.download")}
      </Button>
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
  return (
    <div className="space-y-4">
      <p>{t("dataTransfer.export.intro")}</p>
      <Button onClick={() => request.mutate()} disabled={request.isPending}>
        {t("dataTransfer.export.request")}
      </Button>
      <ErrorList error={request.error} />
      {!data ? (
        <Spinner />
      ) : (
        <ul className="space-y-3">
          {data.results.map((job) => (
            <li key={job.id} className="space-y-2 rounded-md border border-border p-3">
              <p>
                {formatDateTime(job.created_at, i18n.language)} ·{" "}
                <span role="status">{t(`dataTransfer.export.status.${job.status}`)}</span>
                {job.expires_at && job.status === "ready"
                  ? ` · ${t("dataTransfer.export.expires", {
                      date: formatDate(job.expires_at, i18n.language),
                    })}`
                  : ""}
              </p>
              {job.status === "ready" ? <DownloadExport job={job} /> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
