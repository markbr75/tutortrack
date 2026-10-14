import { ApiError, unwrap, type components, type paths } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, useFeature, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";

type Destination = components["schemas"]["WarehouseDestination"];
type Kind = Destination["kind"];
type DatasetKey = NonNullable<
  NonNullable<
    paths["/api/v1/reporting/warehouse/exports/{id}/download"]["get"]["parameters"]["query"]
  >["dataset"]
>;

const KINDS: Kind[] = ["platform", "s3", "bigquery", "snowflake"];
/** The settings and credentials each destination needs (credentials are write-only). */
const CONFIG: Record<Kind, string[]> = {
  platform: [],
  s3: ["bucket", "region", "prefix"],
  bigquery: ["project", "dataset"],
  snowflake: ["account", "user", "database", "schema", "warehouse"],
};
const SECRETS: Record<Kind, string[]> = {
  platform: [],
  s3: ["access_key_id", "secret_access_key"],
  bigquery: ["client_email", "private_key"],
  snowflake: ["private_key"],
};

function NewDestinationForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<Kind>("platform");
  const [name, setName] = useState("");
  const [hour, setHour] = useState("2");
  const [config, setConfig] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/reporting/warehouse/destinations", {
          body: {
            name,
            kind,
            config,
            credentials: SECRETS[kind].length ? secrets : undefined,
            hour: Number(hour),
            enabled: true,
            full_refresh_weekday: 6,
          },
        }),
      ),
    onSuccess: () => {
      setConfig({});
      setSecrets({});
      setName("");
      onDone();
    },
  });
  return (
    <form
      className="space-y-3 rounded-md border border-border p-4"
      aria-labelledby="new-destination"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <h2 id="new-destination" className="text-lg font-semibold">
        {t("warehouse.newDestination")}
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField
          label={t("warehouse.kind")}
          value={kind}
          options={KINDS.map((k) => ({ value: k, label: t(`warehouse.kinds.${k}`) }))}
          onChange={(e) => setKind(e.target.value as Kind)}
        />
        <TextField
          label={t("warehouse.name")}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <SelectField
          label={t("warehouse.hour")}
          hint={t("warehouse.hourHint")}
          value={hour}
          options={Array.from({ length: 24 }, (_, h) => ({
            value: String(h),
            label: `${String(h).padStart(2, "0")}:00`,
          }))}
          onChange={(e) => setHour(e.target.value)}
        />
        {CONFIG[kind].map((field) => (
          <TextField
            key={field}
            label={t(`warehouse.fields.${field}`)}
            value={config[field] ?? ""}
            required={field !== "prefix"}
            onChange={(e) => setConfig({ ...config, [field]: e.target.value })}
          />
        ))}
        {SECRETS[kind].map((field) => (
          <TextField
            key={field}
            label={t(`warehouse.fields.${field}`)}
            type="password"
            autoComplete="off"
            required
            value={secrets[field] ?? ""}
            onChange={(e) => setSecrets({ ...secrets, [field]: e.target.value })}
          />
        ))}
      </div>
      <Button type="submit" loading={create.isPending}>
        {t("warehouse.save")}
      </Button>
      <ErrorList error={create.error} />
    </form>
  );
}

function ExportsList({ destination }: { destination: Destination }) {
  const { t, i18n } = useTranslation();
  const exports = useQuery({
    queryKey: ["warehouse", "exports", destination.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/reporting/warehouse/destinations/{id}/exports", {
          params: { path: { id: destination.id } },
        }),
      ),
  });
  const download = useMutation({
    mutationFn: async ({ id, dataset }: { id: string; dataset: string }) =>
      unwrap(
        await api.GET("/api/v1/reporting/warehouse/exports/{id}/download", {
          params: {
            path: { id },
            query: {
              dataset: dataset as DatasetKey,
            },
          },
        }),
      ),
    onSuccess: (data) => window.location.assign(data.url),
  });
  const rows = exports.data ?? [];
  if (!rows.length)
    return <p className="text-sm text-muted-foreground">{t("warehouse.noExports")}</p>;
  return (
    <ul className="space-y-2 text-sm">
      {rows.map((run) => (
        <li key={run.id} className="rounded-md border border-border p-2">
          <p>
            {formatDateTime(run.until, i18n.language)} · {t(`warehouse.status.${run.status}`)} ·{" "}
            {t("warehouse.rows", { count: run.row_count })}
            {run.full ? ` · ${t("warehouse.full")}` : ""}
          </p>
          {run.error ? <p className="text-danger">{run.error}</p> : null}
          {destination.kind === "platform" && run.status === "succeeded" ? (
            <p className="flex flex-wrap gap-2">
              {(run.manifest as { dataset: string; rows: number }[])
                .filter((m) => m.rows > 0)
                .map((m) => (
                  <Button
                    key={m.dataset}
                    size="sm"
                    variant="ghost"
                    onClick={() => download.mutate({ id: run.id, dataset: m.dataset })}
                  >
                    {t("warehouse.download", { dataset: m.dataset })}
                  </Button>
                ))}
            </p>
          ) : null}
        </li>
      ))}
      <ErrorList error={download.error} />
    </ul>
  );
}

function DestinationCard({ destination }: { destination: Destination }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["warehouse"] });
  const run = useMutation({
    mutationFn: async (full: boolean) =>
      unwrap(
        await api.POST("/api/v1/reporting/warehouse/destinations/{id}/run", {
          params: { path: { id: destination.id } },
          body: { full },
        }),
      ),
    onSuccess: refresh,
  });
  const check = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/reporting/warehouse/destinations/{id}/check", {
          params: { path: { id: destination.id } },
        }),
      ),
  });
  const remove = useMutation({
    mutationFn: async () =>
      api.DELETE("/api/v1/reporting/warehouse/destinations/{id}", {
        params: { path: { id: destination.id } },
      }),
    onSuccess: refresh,
  });
  return (
    <section
      className="space-y-2 rounded-md border border-border p-4"
      aria-label={destination.name}
    >
      <h2 className="text-lg font-semibold">{destination.name}</h2>
      <p className="text-sm text-muted-foreground">
        {t(`warehouse.kinds.${destination.kind}`)} ·{" "}
        {t("warehouse.nightlyAt", { hour: `${String(destination.hour).padStart(2, "0")}:00` })}
        {destination.last_export_at
          ? ` · ${t("warehouse.lastExport", { when: formatDateTime(destination.last_export_at, i18n.language) })}`
          : ""}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => run.mutate(false)} loading={run.isPending}>
          {t("warehouse.exportNow")}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => run.mutate(true)}>
          {t("warehouse.fullExport")}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => check.mutate()}
          loading={check.isPending}
        >
          {t("warehouse.check")}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => remove.mutate()}>
          {t("warehouse.delete")}
        </Button>
      </div>
      {run.isSuccess ? <Alert tone="success">{t("warehouse.started")}</Alert> : null}
      {check.isSuccess ? <Alert tone="success">{t("warehouse.checkOk")}</Alert> : null}
      <ErrorList error={run.error ?? check.error ?? remove.error} />
      <ExportsList destination={destination} />
    </section>
  );
}

/** Data warehouse export (E26-T09, Enterprise): nightly incremental exports. */
export function WarehousePage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("reporting.warehouse.manage");
  const entitled = useFeature("warehouse_export");
  const destinations = useQuery({
    queryKey: ["warehouse", "destinations"],
    queryFn: async () => unwrap(await api.GET("/api/v1/reporting/warehouse/destinations")),
    enabled: canManage,
  });
  const schema = useQuery({
    queryKey: ["warehouse", "schema"],
    queryFn: async () => unwrap(await api.GET("/api/v1/reporting/warehouse/schema")),
    enabled: canManage,
  });
  if (!canManage) {
    return <Alert tone="warning">{t("warehouse.noPermission")}</Alert>;
  }
  const forbidden = destinations.error instanceof ApiError && destinations.error.status === 403;
  return (
    <div className="max-w-4xl space-y-6">
      <header className="space-y-1">
        <p className="text-sm">
          <Link to="/analytics" className="underline">
            {t("reporting.library")}
          </Link>
        </p>
        <h1 className="text-2xl font-semibold">{t("warehouse.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("warehouse.help")}</p>
      </header>
      {!entitled ? <Alert tone="warning">{t("warehouse.enterpriseOnly")}</Alert> : null}
      {destinations.isPending ? <Spinner className="size-5" label={t("common.loading")} /> : null}
      {!forbidden ? <ErrorList error={destinations.error} /> : null}
      {(destinations.data?.results ?? []).map((d) => (
        <DestinationCard key={d.id} destination={d} />
      ))}
      {entitled ? (
        <NewDestinationForm
          onDone={() => void queryClient.invalidateQueries({ queryKey: ["warehouse"] })}
        />
      ) : null}
      {schema.data ? (
        <details className="rounded-md border border-border p-4 text-sm">
          <summary className="cursor-pointer font-medium">{t("warehouse.schemas")}</summary>
          {schema.data.map((d) => (
            <div key={d.dataset} className="mt-3">
              <h3 className="font-mono font-medium">{d.dataset}</h3>
              <p className="text-muted-foreground">{d.description}</p>
              <p className="font-mono text-xs">
                {(d.columns as { name: string; type: string }[])
                  .map((c) => `${c.name} ${c.type}`)
                  .join(", ")}
              </p>
            </div>
          ))}
        </details>
      ) : null}
    </div>
  );
}
