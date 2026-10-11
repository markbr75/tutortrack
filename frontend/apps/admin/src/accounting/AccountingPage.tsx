import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { SyncBadge } from "./SyncBadge";

type Connection = components["schemas"]["AccountingConnection"];
type MappingSet = components["schemas"]["MappingSet"];
type Chart = components["schemas"]["Chart"];
type Option = { value: string; label: string };
type MappingProvider = "xero" | "quickbooks" | "export";

const RETURN_PATH = "/settings/accounting";
const PROVIDERS = ["xero", "quickbooks"] as const;
const FORMATS = ["generic", "sage50", "myob", "iif"] as const;

/** Finishes connecting Xero/QuickBooks when the provider sends the browser back here
 * (`?code&state`, plus `account_id` for QuickBooks), then sets up our side. */
function useConnectCompletion(onDone: () => void) {
  const started = useRef(false);
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  const state = params.get("state");
  const accountId = params.get("account_id") ?? "";
  const denied = params.get("integration_error");
  const complete = useMutation({
    mutationFn: async () => {
      const connection = unwrap(
        await api.POST("/api/v1/integrations/oauth/complete", {
          body: { code: code ?? "", state: state ?? "", account_id: accountId },
        }),
      );
      return unwrap(
        await api.POST("/api/v1/accounting/connections", {
          body: { connection: connection.id },
        }),
      );
    },
    onSettled: () => {
      window.history.replaceState(null, "", window.location.pathname);
      onDone();
    },
  });
  useEffect(() => {
    if (code && state && !started.current) {
      started.current = true;
      complete.mutate();
    }
  }, [code, state, complete]);
  return { complete, denied };
}

function ConnectButtons() {
  const { t } = useTranslation();
  const start = useMutation({
    mutationFn: async (provider: string) =>
      unwrap(
        await api.POST("/api/v1/integrations/oauth/start", {
          body: { provider, level: "organisation", next: RETURN_PATH },
        }),
      ),
    onSuccess: (result) => window.location.assign(result.authorize_url),
  });
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {PROVIDERS.map((p) => (
          <Button key={p} variant="secondary" onClick={() => start.mutate(p)}>
            {t("accounting.connect", { provider: t(`accounting.providers.${p}`) })}
          </Button>
        ))}
      </div>
      <ErrorList error={start.error} />
    </div>
  );
}

function ConnectionCard({ conn, canManage }: { conn: Connection; canManage: boolean }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const path = { params: { path: { id: conn.id } } };
  const act = useMutation({
    mutationFn: async (kind: "refresh" | "disconnect") =>
      kind === "refresh"
        ? unwrap(await api.POST("/api/v1/accounting/connections/{id}/refresh", path))
        : unwrap(await api.POST("/api/v1/accounting/connections/{id}/disconnect", path)),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["accounting"] }),
  });
  return (
    <section
      className="space-y-2 rounded-md border border-border p-4"
      aria-label={conn.provider_name}
    >
      <h2 className="text-lg font-semibold">{conn.provider_name}</h2>
      <p className="text-sm">
        <span className={conn.status === "active" ? "text-success" : "text-danger"}>
          {t(`integrations.status.${conn.status}`)}
        </span>
        {conn.company_name ? ` · ${conn.company_name}` : ""}
        {conn.base_currency ? ` · ${conn.base_currency}` : ""}
        {conn.last_sync_at
          ? ` · ${t("integrations.lastSync", { when: formatDateTime(conn.last_sync_at, i18n.language) })}`
          : ""}
      </p>
      {conn.lock_date ? (
        <p className="text-sm text-muted-foreground">
          {t("accounting.lockDate", { date: formatDate(conn.lock_date, i18n.language) })}
        </p>
      ) : null}
      {conn.connection_error ? <Alert tone="warning">{conn.connection_error}</Alert> : null}
      {canManage ? (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => act.mutate("refresh")}>
            {t("accounting.refresh")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => act.mutate("disconnect")}>
            {t("integrations.disconnect")}
          </Button>
        </div>
      ) : null}
      <ErrorList error={act.error} />
    </section>
  );
}

function OptionsForm({ conn, canManage }: { conn: Connection; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [values, setValues] = useState({
    mode: conn.mode ?? "individual",
    start_date: conn.start_date ?? "",
    sync_bills: conn.sync_bills ?? true,
    attach_pdf: conn.attach_pdf ?? true,
    lock_behaviour: conn.lock_behaviour ?? "post_to_open",
  });
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/accounting/connections/{id}", {
          params: { path: { id: conn.id } },
          body: { ...values, start_date: values.start_date || null },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["accounting"] }),
  });
  return (
    <form
      className="max-w-md space-y-3"
      aria-labelledby="options-heading"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <h2 id="options-heading" className="text-lg font-semibold">
        {t("accounting.options")}
      </h2>
      <SelectField
        label={t("accounting.mode")}
        value={values.mode}
        disabled={!canManage}
        onChange={(e) => setValues({ ...values, mode: e.target.value as typeof values.mode })}
        options={[
          { value: "individual", label: t("accounting.modes.individual") },
          { value: "summary", label: t("accounting.modes.summary") },
        ]}
      />
      <TextField
        type="date"
        label={t("accounting.startDate")}
        hint={t("accounting.startDateHelp")}
        value={values.start_date}
        disabled={!canManage}
        onChange={(e) => setValues({ ...values, start_date: e.target.value })}
      />
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={values.sync_bills}
          disabled={!canManage}
          onChange={(e) => setValues({ ...values, sync_bills: e.target.checked })}
        />
        {t("accounting.syncBills")}
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={values.attach_pdf}
          disabled={!canManage}
          onChange={(e) => setValues({ ...values, attach_pdf: e.target.checked })}
        />
        {t("accounting.attachPdf")}
      </label>
      <SelectField
        label={t("accounting.lockBehaviour")}
        value={values.lock_behaviour}
        disabled={!canManage}
        onChange={(e) =>
          setValues({ ...values, lock_behaviour: e.target.value as typeof values.lock_behaviour })
        }
        options={[
          { value: "post_to_open", label: t("accounting.lock.post_to_open") },
          { value: "hold", label: t("accounting.lock.hold") },
        ]}
      />
      {canManage ? (
        <Button size="sm" type="submit" disabled={save.isPending}>
          {t("common.save")}
        </Button>
      ) : null}
      {save.isSuccess ? <p role="status">{t("accounting.saved")}</p> : null}
      <ErrorList error={save.error} />
    </form>
  );
}

function rowKey(kind: string, key: string) {
  return `${kind}|${key}`;
}

/** Account per kind (and per service category, product category or payment method),
 * tax code per tax rate, tracking option per branch (FR-23-1). With `chart`, choices
 * come from the ledger; without (GL exports), codes are typed in. */
export function MappingsForm({
  provider,
  chart,
  canManage,
}: {
  provider: MappingProvider;
  chart?: Chart;
  canManage: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const path = { params: { path: { provider } } };
  const set = useQuery({
    queryKey: ["accounting", "mappings", provider],
    queryFn: async () => unwrap(await api.GET("/api/v1/accounting/mappings/{provider}", path)),
  });
  const [accounts, setAccounts] = useState<Record<string, string>>({});
  const [taxes, setTaxes] = useState<Record<string, string>>({});
  const [tracking, setTracking] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!set.data) return;
    setAccounts(
      Object.fromEntries(
        set.data.accounts.map((a) => [rowKey(a.kind, a.key ?? "default"), a.external_id]),
      ),
    );
    setTaxes(Object.fromEntries(set.data.taxes.map((x) => [x.tax_rate ?? "", x.external_id])));
    setTracking(Object.fromEntries(set.data.tracking.map((x) => [x.branch, x.option_id])));
  }, [set.data]);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/accounting/mappings/{provider}", {
          ...path,
          body: {
            accounts: Object.entries(accounts)
              .filter(([, v]) => v)
              .map(([k, v]) => {
                const [kind, key] = k.split("|");
                return { kind: kind!, key: key!, external_id: v };
              }),
            taxes: Object.entries(taxes)
              .filter(([, v]) => v)
              .map(([rate, v]) => ({ tax_rate: rate || null, external_id: v })),
            tracking: Object.entries(tracking)
              .filter(([, v]) => v)
              .map(([branch, option]) => ({
                branch,
                category_id:
                  chart?.tracking.find((c) => c.options.some((o) => o[0] === option))?.id ?? "",
                option_id: option,
              })),
          },
        }),
      ),
    onSuccess: (data: MappingSet) => {
      queryClient.setQueryData(["accounting", "mappings", provider], data);
      void queryClient.invalidateQueries({ queryKey: ["accounting", "connections"] });
    },
  });
  if (set.isPending) return <Spinner className="size-4" label={t("grid.loading")} />;
  if (!set.data) return <ErrorList error={set.error} />;
  const data = set.data;
  const accountOptions: Option[] = [
    { value: "", label: t("accounting.notMapped") },
    ...(chart?.accounts ?? [])
      .filter((a) => a.active)
      .map((a) => ({ value: a.id, label: a.code ? `${a.code} · ${a.name}` : a.name })),
  ];
  const taxOptions: Option[] = [
    { value: "", label: t("accounting.notMapped") },
    ...(chart?.tax_codes ?? [])
      .filter((x) => x.active)
      .map((x) => ({ value: x.id, label: x.name })),
  ];
  const trackingOptions: Option[] = [
    { value: "", label: t("accounting.noTracking") },
    ...(chart?.tracking ?? []).flatMap((c) =>
      c.options.map((o) => ({ value: o[0]!, label: `${c.name}: ${o[1]}` })),
    ),
  ];
  const field = (
    id: string,
    label: string,
    value: string,
    onChange: (v: string) => void,
    options: Option[],
  ) =>
    chart ? (
      <SelectField
        key={id}
        label={label}
        value={value}
        disabled={!canManage}
        onChange={(e) => onChange(e.target.value)}
        options={options}
      />
    ) : (
      <TextField
        key={id}
        label={label}
        value={value}
        disabled={!canManage}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  const account = (kind: string, key: string, label: string) =>
    field(
      rowKey(kind, key),
      label,
      accounts[rowKey(kind, key)] ?? "",
      (v) => setAccounts({ ...accounts, [rowKey(kind, key)]: v }),
      accountOptions,
    );
  return (
    <form
      className="space-y-4"
      aria-label={t("accounting.mappingsFor", { provider: t(`accounting.providers.${provider}`) })}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {data.problems.length ? (
        <Alert tone="warning">
          <p className="font-medium">{t("accounting.problems")}</p>
          <ul className="list-disc pl-5">
            {data.problems.map((p) => (
              <li key={`${p.kind}-${p.key}`}>{p.message}</li>
            ))}
          </ul>
        </Alert>
      ) : (
        <p role="status" className="text-sm text-success">
          {t("accounting.mappingsComplete")}
        </p>
      )}
      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-2 font-medium">{t("accounting.accounts")}</legend>
        {data.kinds
          .filter((k) => provider !== "export" || k.kind !== "expense")
          .map((k) => account(k.kind, "default", k.is_required ? `${k.name} *` : k.name))}
        {chart
          ? field(
              "purchase_tax",
              t("accounting.purchaseTax"),
              accounts[rowKey("purchase_tax", "default")] ?? "",
              (v) => setAccounts({ ...accounts, [rowKey("purchase_tax", "default")]: v }),
              taxOptions,
            )
          : null}
      </fieldset>
      <details className="rounded-md border border-border p-3">
        <summary className="cursor-pointer text-sm font-medium">{t("accounting.specific")}</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {data.revenue_keys.map((k) =>
            account("revenue", k.key, t("accounting.revenueFor", { name: k.name })),
          )}
          {data.clearing_keys.map((k) =>
            account("clearing", k.key, t("accounting.clearingFor", { name: k.name })),
          )}
          {data.expense_keys.map((k) =>
            account("expense", k.key, t("accounting.expenseFor", { name: k.name })),
          )}
        </div>
      </details>
      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-2 font-medium">{t("accounting.taxes")}</legend>
        {[{ key: "", name: t("accounting.noTax") }, ...data.tax_rates].map((r) =>
          field(
            `tax-${r.key}`,
            r.name,
            taxes[r.key] ?? "",
            (v) => setTaxes({ ...taxes, [r.key]: v }),
            taxOptions,
          ),
        )}
      </fieldset>
      {chart && chart.tracking.length && data.branches.length > 1 ? (
        <fieldset className="grid gap-3 sm:grid-cols-2">
          <legend className="mb-2 font-medium">{t("accounting.tracking")}</legend>
          {data.branches.map((b) =>
            field(
              `branch-${b.key}`,
              b.name,
              tracking[b.key] ?? "",
              (v) => setTracking({ ...tracking, [b.key]: v }),
              trackingOptions,
            ),
          )}
        </fieldset>
      ) : null}
      {canManage ? (
        <Button size="sm" type="submit" disabled={save.isPending}>
          {t("accounting.saveMappings")}
        </Button>
      ) : null}
      {save.isSuccess ? <p role="status">{t("accounting.saved")}</p> : null}
      <ErrorList error={save.error} />
    </form>
  );
}

function SyncSwitch({ conn, canManage }: { conn: Connection; canManage: boolean }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [backfillFrom, setBackfillFrom] = useState("");
  const path = { params: { path: { id: conn.id } } };
  const act = useMutation({
    mutationFn: async (kind: "enable" | "disable" | "cancel") => {
      if (kind === "enable")
        return unwrap(
          await api.POST("/api/v1/accounting/connections/{id}/enable", {
            ...path,
            body: { backfill_from: backfillFrom || null },
          }),
        );
      if (kind === "cancel")
        return unwrap(await api.POST("/api/v1/accounting/connections/{id}/cancel-backfill", path));
      return unwrap(await api.POST("/api/v1/accounting/connections/{id}/disable", path));
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["accounting"] }),
  });
  const progress = conn.backfill_progress;
  return (
    <section className="space-y-3" aria-labelledby="sync-heading">
      <h2 id="sync-heading" className="text-lg font-semibold">
        {t("accounting.sync")}
      </h2>
      <p className="text-sm" role="status">
        {conn.enabled
          ? t("accounting.syncOn", {
              date: conn.start_date ? formatDate(conn.start_date, i18n.language) : "—",
            })
          : t("accounting.syncOff")}
      </p>
      {canManage && !conn.enabled ? (
        <div className="flex flex-wrap items-end gap-2">
          <TextField
            type="date"
            label={t("accounting.backfillFrom")}
            hint={t("accounting.backfillHelp")}
            value={backfillFrom}
            onChange={(e) => setBackfillFrom(e.target.value)}
          />
          <Button onClick={() => act.mutate("enable")} disabled={conn.problems.length > 0}>
            {t("accounting.enable")}
          </Button>
        </div>
      ) : null}
      {canManage && conn.enabled ? (
        <Button size="sm" variant="secondary" onClick={() => act.mutate("disable")}>
          {t("accounting.disable")}
        </Button>
      ) : null}
      {progress?.status ? (
        <p className="text-sm">
          {t(`accounting.backfill.${progress.status}`, {
            synced: progress.synced ?? 0,
            failed: progress.failed ?? 0,
          })}{" "}
          {progress.status === "running" && canManage ? (
            <Button size="sm" variant="ghost" onClick={() => act.mutate("cancel")}>
              {t("accounting.cancelBackfill")}
            </Button>
          ) : null}
        </p>
      ) : null}
      <ErrorList error={act.error} />
    </section>
  );
}

/** Counts by status, errors with retry/skip, and the latest synced records (FR-23-3). */
function SyncDashboard({ conn, canManage }: { conn: Connection; canManage: boolean }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const errors = useQuery({
    queryKey: ["accounting", "records", "error"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/accounting/records", { params: { query: { status: "error" } } }),
      ).results,
  });
  const recent = useQuery({
    queryKey: ["accounting", "records", "recent"],
    queryFn: async () => unwrap(await api.GET("/api/v1/accounting/records")).results.slice(0, 20),
  });
  const act = useMutation({
    mutationFn: async ({ id, kind }: { id?: string; kind: "retry" | "skip" | "all" }) => {
      if (kind === "all") return unwrap(await api.POST("/api/v1/accounting/records/retry-failed"));
      const path = { params: { path: { id: id! } } };
      return kind === "retry"
        ? unwrap(await api.POST("/api/v1/accounting/records/{id}/retry", path))
        : unwrap(
            await api.POST("/api/v1/accounting/records/{id}/skip", {
              ...path,
              body: { reason: "" },
            }),
          );
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["accounting"] }),
  });
  return (
    <section className="space-y-3" aria-labelledby="dashboard-heading">
      <h2 id="dashboard-heading" className="text-lg font-semibold">
        {t("accounting.dashboard")}
      </h2>
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {(["synced", "pending", "error", "skipped"] as const).map((s) => (
          <div key={s} className="rounded-md border border-border p-2">
            <dt className="text-muted-foreground">{t(`accounting.status.${s}`)}</dt>
            <dd className="text-lg font-semibold">{conn.stats[s]}</dd>
          </div>
        ))}
      </dl>
      <h3 className="font-medium">{t("accounting.errors")}</h3>
      {errors.data?.length ? (
        <>
          <ul className="divide-y divide-border rounded-md border border-border text-sm">
            {errors.data.map((r) => (
              <li key={r.id} className="space-y-1 p-3">
                <p className="font-medium">{r.label}</p>
                <p className="text-danger">{r.error}</p>
                {canManage ? (
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => act.mutate({ id: r.id, kind: "retry" })}
                    >
                      {t("accounting.retry")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => act.mutate({ id: r.id, kind: "skip" })}
                    >
                      {t("accounting.skip")}
                    </Button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
          {canManage ? (
            <Button size="sm" variant="secondary" onClick={() => act.mutate({ kind: "all" })}>
              {t("accounting.retryAll")}
            </Button>
          ) : null}
        </>
      ) : (
        <p className="text-sm text-muted-foreground">{t("accounting.noErrors")}</p>
      )}
      <ErrorList error={act.error} />
      <h3 className="font-medium">{t("accounting.recent")}</h3>
      <ul className="divide-y divide-border rounded-md border border-border text-sm">
        {(recent.data ?? []).map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 p-2">
            <span>
              {r.label}
              {r.external_number ? ` · ${r.external_number}` : ""}
            </span>
            <span className="flex items-center gap-2">
              <span className="text-muted-foreground">
                {formatDateTime(r.updated_at, i18n.language)}
              </span>
              <SyncBadge record={r} />
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** General ledger exports for other packages (FR-23-5). */
function ExportSection({ connectedProvider }: { connectedProvider?: string }) {
  const { t } = useTranslation();
  const canManage = usePermission("integrations.accounting.manage");
  const [fmt, setFmt] = useState<string>("generic");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [mappingSet, setMappingSet] = useState(connectedProvider ?? "export");
  const href = `/api/v1/accounting/export?${new URLSearchParams({
    file_format: fmt,
    start,
    end,
    mapping_set: mappingSet,
  }).toString()}`;
  return (
    <section className="space-y-3" aria-labelledby="export-heading">
      <h2 id="export-heading" className="text-lg font-semibold">
        {t("accounting.export")}
      </h2>
      <p className="text-sm text-muted-foreground">{t("accounting.exportHelp")}</p>
      <div className="grid max-w-xl gap-3 sm:grid-cols-2">
        <TextField
          type="date"
          label={t("accounting.from")}
          value={start}
          onChange={(e) => setStart(e.target.value)}
        />
        <TextField
          type="date"
          label={t("accounting.to")}
          value={end}
          onChange={(e) => setEnd(e.target.value)}
        />
        <SelectField
          label={t("accounting.format")}
          value={fmt}
          onChange={(e) => setFmt(e.target.value)}
          options={FORMATS.map((f) => ({ value: f, label: t(`accounting.formats.${f}`) }))}
        />
        <SelectField
          label={t("accounting.mappingSet")}
          value={mappingSet}
          onChange={(e) => setMappingSet(e.target.value)}
          options={[
            { value: "export", label: t("accounting.exportCodes") },
            ...(connectedProvider
              ? [
                  {
                    value: connectedProvider,
                    label: t(`accounting.providers.${connectedProvider}`),
                  },
                ]
              : []),
          ]}
        />
      </div>
      {start && end ? (
        <a className="inline-block font-medium underline" href={href} download>
          {t("accounting.download")}
        </a>
      ) : null}
      {mappingSet === "export" ? (
        <details className="rounded-md border border-border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            {t("accounting.exportCodes")}
          </summary>
          <div className="mt-3">
            <MappingsForm provider="export" canManage={canManage} />
          </div>
        </details>
      ) : null}
    </section>
  );
}

/** Settings → Accounting (E23): connect Xero or QuickBooks Online, map accounts and tax
 * codes, choose what syncs, switch sync on (with optional backfill), watch and fix the
 * sync, and download GL exports. */
export function AccountingPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("integrations.accounting.manage");
  const canExport = usePermission("integrations.accounting.export");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["accounting"] });
  const { complete, denied } = useConnectCompletion(refresh);
  const connections = useQuery({
    queryKey: ["accounting", "connections"],
    queryFn: async () => unwrap(await api.GET("/api/v1/accounting/connections")).results,
  });
  const conn = connections.data?.[0];
  const chart = useQuery({
    queryKey: ["accounting", "chart", conn?.id],
    enabled: Boolean(conn),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/accounting/connections/{id}/chart", {
          params: { path: { id: conn!.id } },
        }),
      ),
  });
  return (
    <div className="max-w-4xl space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("accounting.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("accounting.help")}</p>
      </header>
      {conn?.simulated ? <Alert>{t("accounting.simulated")}</Alert> : null}
      {complete.isPending ? (
        <Spinner className="size-5" label={t("integrations.finishing")} />
      ) : null}
      {complete.isSuccess ? <Alert tone="success">{t("accounting.connected")}</Alert> : null}
      {denied ? <Alert tone="warning">{t("integrations.denied")}</Alert> : null}
      <ErrorList error={complete.error ?? connections.error} />
      {connections.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      {connections.data && !conn ? (
        canManage ? (
          <ConnectButtons />
        ) : (
          <p className="text-sm text-muted-foreground">{t("accounting.notConnected")}</p>
        )
      ) : null}
      {conn ? (
        <>
          <ConnectionCard conn={conn} canManage={canManage} />
          <OptionsForm key={`${conn.id}-${conn.mode}`} conn={conn} canManage={canManage} />
          <section className="space-y-3" aria-labelledby="mappings-heading">
            <h2 id="mappings-heading" className="text-lg font-semibold">
              {t("accounting.mappings")}
            </h2>
            {chart.data ? (
              <MappingsForm
                provider={conn.provider as MappingProvider}
                chart={chart.data}
                canManage={canManage}
              />
            ) : (
              <Spinner className="size-4" label={t("grid.loading")} />
            )}
          </section>
          <SyncSwitch conn={conn} canManage={canManage} />
          <SyncDashboard conn={conn} canManage={canManage} />
        </>
      ) : null}
      {canExport ? <ExportSection connectedProvider={conn?.provider} /> : null}
    </div>
  );
}
