import { ApiError, unwrap, type components, type paths } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  Disclosure,
  FormPanel,
  figureCell,
  PanelRow,
  PanelRows,
  RuledPanel,
  RuledTable,
  SelectField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, useFeature, usePermission } from "../api";
import { PanelLoading } from "../billing/moneyUi";
import { useIsPhone } from "../billing/useIsPhone";
import { ErrorList } from "../calendar/ErrorList";
import { ReportsPage } from "./ReportingPages";

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
    <FormPanel
      title={t("warehouse.newDestination")}
      submit={t("warehouse.save")}
      pending={create.isPending}
      onSubmit={() => create.mutate()}
      error={create.error ? <ErrorList error={create.error} /> : null}
    >
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
        className="tabular-nums"
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
    </FormPanel>
  );
}

/** A destination's exports: when, the status in words, rows and (for downloads) the files. */
function ExportsTable({ destination }: { destination: Destination }) {
  const { t, i18n } = useTranslation();
  const phone = useIsPhone();
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
  const files = destination.kind === "platform";
  return (
    <>
      <RuledTable
        caption={t("designS9a.exportsOf", { name: destination.name })}
        loading={exports.isPending}
        loadingLabel={t("grid.loading")}
        empty={!exports.isPending && !rows.length ? t("warehouse.noExports") : undefined}
        columns={[
          { key: "when", header: t("designS9a.until"), width: "min-w-40" },
          { key: "status", header: t("designS9a.status") },
          ...(phone ? [] : [{ key: "rows", header: t("designS9a.rowsHeading"), end: true }]),
          ...(files && !phone ? [{ key: "files", header: t("designS9a.files") }] : []),
        ]}
      >
        {rows.map((run) => {
          const datasets =
            files && run.status === "succeeded"
              ? (run.manifest as { dataset: string; rows: number }[]).filter((m) => m.rows > 0)
              : [];
          const links = datasets.length ? (
            <span className="flex flex-wrap gap-x-3 gap-y-1">
              {datasets.map((m) => (
                <button
                  key={m.dataset}
                  type="button"
                  className="text-link hover:underline"
                  onClick={() => download.mutate({ id: run.id, dataset: m.dataset })}
                >
                  {t("warehouse.download", { dataset: m.dataset })}
                </button>
              ))}
            </span>
          ) : null;
          return (
            <tr key={run.id}>
              <td>
                <span className="whitespace-nowrap tabular-nums">
                  {formatDateTime(run.until, i18n.language)}
                </span>
                {run.full || phone ? (
                  <span className="block text-xs text-muted-foreground">
                    {[
                      run.full ? t("designS9a.fullExport") : null,
                      phone ? t("warehouse.rows", { count: run.row_count }) : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                ) : null}
                {phone && links ? <span className="mt-1 block">{links}</span> : null}
              </td>
              <td>
                <span className={run.status === "failed" ? "font-medium text-danger" : undefined}>
                  {t(`warehouse.status.${run.status}`)}
                </span>
                {run.error ? <span className="block text-xs text-danger">{run.error}</span> : null}
              </td>
              {phone ? null : <td className={figureCell}>{run.row_count}</td>}
              {files && !phone ? <td>{links}</td> : null}
            </tr>
          );
        })}
      </RuledTable>
      {download.error ? (
        <div className="px-5 pb-4">
          <ErrorList error={download.error} />
        </div>
      ) : null}
    </>
  );
}

function DestinationPanel({ destination }: { destination: Destination }) {
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
  const error = run.error ?? check.error ?? remove.error;
  return (
    <RuledPanel
      title={destination.name}
      description={[
        t(`warehouse.kinds.${destination.kind}`),
        t("warehouse.nightlyAt", { hour: `${String(destination.hour).padStart(2, "0")}:00` }),
        destination.last_export_at
          ? t("warehouse.lastExport", {
              when: formatDateTime(destination.last_export_at, i18n.language),
            })
          : null,
      ]
        .filter(Boolean)
        .join(" · ")}
      flush
      footer={
        <>
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
          <Button size="sm" onClick={() => run.mutate(false)} loading={run.isPending}>
            {t("warehouse.exportNow")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            onClick={() => remove.mutate()}
          >
            {t("warehouse.delete")}
          </Button>
          {run.isSuccess ? (
            <span role="status" className="text-success">
              {t("warehouse.started")}
            </span>
          ) : null}
          {check.isSuccess ? (
            <span role="status" className="text-success">
              {t("warehouse.checkOk")}
            </span>
          ) : null}
        </>
      }
    >
      <ExportsTable destination={destination} />
      {error ? (
        <div className="px-5 pb-4">
          <ErrorList error={error} />
        </div>
      ) : null}
    </RuledPanel>
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
  const forbidden = destinations.error instanceof ApiError && destinations.error.status === 403;
  return (
    <ReportsPage title={t("warehouse.title")} description={t("warehouse.help")}>
      {!canManage ? (
        <Alert tone="warning">{t("warehouse.noPermission")}</Alert>
      ) : (
        <>
          {!entitled ? <Alert tone="warning">{t("warehouse.enterpriseOnly")}</Alert> : null}
          {destinations.isPending ? (
            <RuledPanel label={t("warehouse.title")} flush>
              <PanelLoading label={t("common.loading")} />
            </RuledPanel>
          ) : null}
          {!forbidden ? <ErrorList error={destinations.error} /> : null}
          {(destinations.data?.results ?? []).map((d) => (
            <DestinationPanel key={d.id} destination={d} />
          ))}
          {entitled ? (
            <NewDestinationForm
              onDone={() => void queryClient.invalidateQueries({ queryKey: ["warehouse"] })}
            />
          ) : null}
          {schema.data ? (
            <RuledPanel label={t("warehouse.schemas")} flush>
              <Disclosure
                summary={t("warehouse.schemas")}
                className="px-5 py-3.5"
                bodyClassName="-mx-5 -mb-3.5 border-t border-border"
              >
                <PanelRows>
                  {schema.data.map((d) => (
                    <PanelRow key={d.dataset}>
                      <h3 className="font-mono font-medium">{d.dataset}</h3>
                      <p className="text-muted-foreground">{d.description}</p>
                      <p className="mt-1 font-mono text-xs break-words text-muted-foreground">
                        {(d.columns as { name: string; type: string }[])
                          .map((c) => `${c.name} ${c.type}`)
                          .join(", ")}
                      </p>
                    </PanelRow>
                  ))}
                </PanelRows>
              </Disclosure>
            </RuledPanel>
          ) : null}
        </>
      )}
    </ReportsPage>
  );
}
