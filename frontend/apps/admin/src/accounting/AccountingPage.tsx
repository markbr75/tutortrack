import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FigureStrip,
  PageHeader,
  PanelFooter,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
  buttonClass,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { KeyedSettings } from "../g3/KeyedSettings";
import { BranchLedgers, LedgerPicker } from "./BranchLedgers";
import { ledgerLabel, useBranches } from "./ledgers";
import { ReadBackSection } from "./ReadBackSection";
import { SyncBadge } from "./SyncBadge";
import { providerName } from "./providerName";

type Connection = components["schemas"]["AccountingConnection"];
type MappingSet = components["schemas"]["MappingSet"];
type Chart = components["schemas"]["Chart"];
type Option = { value: string; label: string };
// A provider, "export", or "<provider>@<branch id>" for a branch's own ledger (gap G5).
type MappingProvider = string;

const RETURN_PATH = "/settings/accounting";
const PROVIDERS = ["xero", "quickbooks", "sage", "freeagent"] as const;
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
    <RuledPanel
      title={t("designS7.accounting.connectTitle")}
      footer={PROVIDERS.map((p) => (
        <Button key={p} variant="secondary" onClick={() => start.mutate(p)}>
          {t("accounting.connect", { provider: providerName(t, p) })}
        </Button>
      ))}
    >
      <p className="text-sm text-muted-foreground">{t("accounting.notConnected")}</p>
      <ErrorList error={start.error} />
    </RuledPanel>
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
  const facts = [
    conn.company_name,
    conn.base_currency,
    conn.last_sync_at
      ? t("integrations.lastSync", { when: formatDateTime(conn.last_sync_at, i18n.language) })
      : "",
  ].filter(Boolean);
  return (
    <RuledPanel
      title={ledgerLabel(t, conn)}
      aside={
        <span className={conn.status === "active" ? "" : "font-medium text-danger"}>
          {t(`integrations.status.${conn.status}`)}
        </span>
      }
      footer={
        canManage ? (
          <>
            <Button size="sm" variant="secondary" onClick={() => act.mutate("refresh")}>
              {t("accounting.refresh")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => act.mutate("disconnect")}>
              {t("integrations.disconnect")}
            </Button>
          </>
        ) : undefined
      }
    >
      <div className="space-y-2 text-sm">
        {facts.length ? <p className="tabular-nums">{facts.join(" · ")}</p> : null}
        {conn.lock_date ? (
          <p className="text-muted-foreground tabular-nums">
            {t("accounting.lockDate", { date: formatDate(conn.lock_date, i18n.language) })}
          </p>
        ) : null}
        {conn.connection_error ? <Alert tone="warning">{conn.connection_error}</Alert> : null}
        <ErrorList error={act.error} />
      </div>
    </RuledPanel>
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
    <RuledPanel flush titleId="options-heading" title={t("accounting.options")}>
      <form
        aria-labelledby="options-heading"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="max-w-md space-y-4 px-5 py-4">
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
              className="size-4"
              checked={values.sync_bills}
              disabled={!canManage}
              onChange={(e) => setValues({ ...values, sync_bills: e.target.checked })}
            />
            {t("accounting.syncBills")}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
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
              setValues({
                ...values,
                lock_behaviour: e.target.value as typeof values.lock_behaviour,
              })
            }
            options={[
              { value: "post_to_open", label: t("accounting.lock.post_to_open") },
              { value: "hold", label: t("accounting.lock.hold") },
            ]}
          />
          <ErrorList error={save.error} />
        </div>
        {canManage ? (
          <PanelFooter>
            <Button type="submit" disabled={save.isPending}>
              {t("common.save")}
            </Button>
            {save.isSuccess ? (
              <p role="status" className="text-success">
                {t("accounting.saved")}
              </p>
            ) : null}
          </PanelFooter>
        ) : null}
      </form>
    </RuledPanel>
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
  if (set.isPending) return <Spinner label={t("grid.loading")} />;
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
      className="space-y-5"
      aria-label={t("accounting.mappingsFor", {
        provider: providerName(t, provider.split("@")[0] ?? provider),
      })}
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
        <p role="status" className="text-sm">
          {t("accounting.mappingsComplete")}
        </p>
      )}
      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-1 text-sm font-semibold">{t("accounting.accounts")}</legend>
        {data.kinds
          .filter((k) => provider !== "export" || k.kind !== "expense")
          .map((k) => account(k.kind, "default", k.is_required ? `${k.name} *` : k.name))}
        {field(
          "purchase_tax",
          t("accounting.purchaseTax"),
          accounts[rowKey("purchase_tax", "default")] ?? "",
          (v) => setAccounts({ ...accounts, [rowKey("purchase_tax", "default")]: v }),
          taxOptions,
        )}
      </fieldset>
      <details className="border-y border-rule py-3">
        <summary className="cursor-pointer text-sm font-medium text-link">
          {t("accounting.specific")}
        </summary>
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
        <legend className="mb-1 text-sm font-semibold">{t("accounting.taxes")}</legend>
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
          <legend className="mb-1 text-sm font-semibold">{t("accounting.tracking")}</legend>
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
      <ErrorList error={save.error} />
      {canManage ? (
        <div className="flex flex-wrap items-center gap-3 border-t border-rule pt-4 text-sm">
          <Button type="submit" disabled={save.isPending}>
            {t("accounting.saveMappings")}
          </Button>
          {save.isSuccess ? (
            <p role="status" className="text-success">
              {t("accounting.saved")}
            </p>
          ) : null}
        </div>
      ) : null}
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
    <RuledPanel titleId="sync-heading" title={t("accounting.sync")} bodyClassName="space-y-3">
      <p className="text-sm tabular-nums" role="status">
        {conn.enabled
          ? t("accounting.syncOn", {
              date: conn.start_date ? formatDate(conn.start_date, i18n.language) : "—",
            })
          : t("accounting.syncOff")}
      </p>
      {canManage && !conn.enabled ? (
        <div className="flex flex-wrap items-start gap-2">
          <TextField
            type="date"
            label={t("accounting.backfillFrom")}
            hint={t("accounting.backfillHelp")}
            value={backfillFrom}
            onChange={(e) => setBackfillFrom(e.target.value)}
          />
          <Button
            className="sm:mt-6"
            onClick={() => act.mutate("enable")}
            disabled={conn.problems.length > 0}
          >
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
        <p className="text-sm tabular-nums">
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
    </RuledPanel>
  );
}

/** Counts by status, errors with retry/skip, and the latest synced records (FR-23-3). */
function SyncDashboard({ conn, canManage }: { conn: Connection; canManage: boolean }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const errors = useQuery({
    queryKey: ["accounting", "records", "error", conn.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/accounting/records", {
          params: { query: { status: "error", connection: conn.id } },
        }),
      ).results,
  });
  const recent = useQuery({
    queryKey: ["accounting", "records", "recent", conn.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/accounting/records", {
          params: { query: { connection: conn.id } },
        }),
      ).results.slice(0, 20),
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
  const errorCount = Number(conn.stats.error ?? 0);
  return (
    <RuledPanel flush titleId="dashboard-heading" title={t("accounting.dashboard")}>
      <div className="px-5">
        <FigureStrip
          label={t("accounting.dashboard")}
          className="border-0"
          figures={(["synced", "pending", "error", "skipped"] as const).map((s) => ({
            key: s,
            label: t(`accounting.status.${s}`),
            value: conn.stats[s],
            tone: s === "error" && errorCount > 0 ? "danger" : "default",
          }))}
        />
      </div>
      <div className="border-t border-border">
        <h3 className="px-5 pt-3.5 pb-1 text-sm font-semibold">{t("accounting.errors")}</h3>
        {errors.data?.length ? (
          <>
            <ul className="text-sm">
              {errors.data.map((r) => (
                <li
                  key={r.id}
                  className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 border-t border-rule px-5 py-2.5 first:border-0"
                >
                  <div className="min-w-0">
                    <p className="font-medium">{r.label}</p>
                    <p className="text-xs text-danger">{r.error}</p>
                  </div>
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
              <PanelFooter>
                <Button size="sm" variant="secondary" onClick={() => act.mutate({ kind: "all" })}>
                  {t("accounting.retryAll")}
                </Button>
              </PanelFooter>
            ) : null}
          </>
        ) : (
          <p className="px-5 pb-3.5 text-sm text-muted-foreground">{t("accounting.noErrors")}</p>
        )}
        {act.error ? (
          <div className="px-5 pb-3">
            <ErrorList error={act.error} />
          </div>
        ) : null}
      </div>
      <div className="border-t border-border">
        <h3 className="px-5 pt-3.5 pb-1 text-sm font-semibold">{t("accounting.recent")}</h3>
        {recent.data?.length ? (
          <ul className="text-sm">
            {recent.data.map((r) => (
              <li
                key={r.id}
                className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-rule px-5 py-2.5 first:border-0"
              >
                <span className="min-w-0">
                  {r.label}
                  {r.external_number ? (
                    <span className="text-muted-foreground tabular-nums">
                      {" "}
                      · {r.external_number}
                    </span>
                  ) : null}
                </span>
                <span className="flex items-center gap-3">
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {formatDateTime(r.updated_at, i18n.language)}
                  </span>
                  <SyncBadge record={r} />
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-5 pb-3.5 text-sm text-muted-foreground">
            {recent.isPending ? t("grid.loading") : t("designS7.accounting.noRecent")}
          </p>
        )}
      </div>
    </RuledPanel>
  );
}

/** General ledger exports for other packages (FR-23-5). */
function ExportSection({ connections }: { connections: Connection[] }) {
  const { t } = useTranslation();
  const canManage = usePermission("integrations.accounting.manage");
  const branches = useBranches();
  const [fmt, setFmt] = useState<string>("generic");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [mappingSet, setMappingSet] = useState(connections[0]?.mapping_set ?? "export");
  const [branch, setBranch] = useState("");
  const href = `/api/v1/accounting/export?${new URLSearchParams({
    file_format: fmt,
    start,
    end,
    mapping_set: mappingSet,
    ...(branch ? { branch } : {}),
  }).toString()}`;
  return (
    <RuledPanel
      flush
      titleId="export-heading"
      title={t("accounting.export")}
      description={t("accounting.exportHelp")}
    >
      <div className="grid max-w-xl gap-4 px-5 py-4 sm:grid-cols-2">
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
            ...connections.map((c) => ({ value: c.mapping_set, label: ledgerLabel(t, c) })),
          ]}
        />
        {(branches.data?.length ?? 0) > 1 ? (
          <SelectField
            label={t("accountingG5.exportBranch")}
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            options={[
              { value: "", label: t("accountingG5.allBranches") },
              ...(branches.data ?? []).map((b) => ({ value: b.id, label: b.name })),
            ]}
          />
        ) : null}
      </div>
      <PanelFooter>
        {start && end ? (
          <a className={buttonClass()} href={href} download>
            {t("accounting.download")}
          </a>
        ) : (
          <p className="text-muted-foreground">{t("designS7.accounting.pickDates")}</p>
        )}
      </PanelFooter>
      {mappingSet === "export" ? (
        <details className="border-t border-border px-5 py-3.5">
          <summary className="cursor-pointer text-sm font-medium text-link">
            {t("accounting.exportCodes")}
          </summary>
          <div className="mt-4">
            <MappingsForm provider="export" canManage={canManage} />
          </div>
        </details>
      ) : null}
    </RuledPanel>
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
  const [selected, setSelected] = useState("");
  const all = connections.data ?? [];
  // The organisation's ledger first; branches' own ledgers are picked above (gap G5).
  const conn = all.find((c) => c.id === selected) ?? all.find((c) => !c.branch) ?? all[0];
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
    <div className="max-w-4xl space-y-6">
      <PageHeader
        title={t("accounting.title")}
        description={t("accounting.help")}
        actions={
          <Link
            to="/settings/accounting/payroll"
            className={buttonClass({ variant: "secondary", size: "sm" })}
          >
            {t("accountingPhase3.payrollLink")}
          </Link>
        }
      />
      {conn?.simulated ? <Alert>{t("accounting.simulated")}</Alert> : null}
      {complete.isPending ? <Spinner label={t("integrations.finishing")} /> : null}
      {complete.isSuccess ? <Alert tone="success">{t("accounting.connected")}</Alert> : null}
      {denied ? <Alert tone="warning">{t("integrations.denied")}</Alert> : null}
      <ErrorList error={complete.error ?? connections.error} />
      {connections.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {connections.data && !conn ? (
        canManage ? (
          <ConnectButtons />
        ) : (
          <p className="text-sm text-muted-foreground">{t("accounting.notConnected")}</p>
        )
      ) : null}
      {conn ? (
        <>
          <LedgerPicker connections={all} value={conn.id} onChange={setSelected} />
          <ConnectionCard conn={conn} canManage={canManage} />
          <OptionsForm key={`${conn.id}-${conn.mode}`} conn={conn} canManage={canManage} />
          <RuledPanel titleId="mappings-heading" title={t("accounting.mappings")}>
            {chart.data ? (
              <MappingsForm
                key={conn.mapping_set}
                provider={conn.mapping_set}
                chart={chart.data}
                canManage={canManage}
              />
            ) : (
              <Spinner label={t("grid.loading")} />
            )}
          </RuledPanel>
          <SyncSwitch key={`switch-${conn.id}`} conn={conn} canManage={canManage} />
          <SyncDashboard conn={conn} canManage={canManage} />
          <ReadBackSection conn={conn} canManage={canManage} />
          {canManage ? <BranchLedgers connections={all} /> : null}
        </>
      ) : null}
      <RuledPanel
        titleId="g3-deferred"
        title={t("g3.accounting.packages")}
        description={t("g3.accounting.packagesHelp")}
      >
        <KeyedSettings
          area="accounting"
          keys={["accounting.package_deferred_revenue"]}
          label={t("g3.accounting.packages")}
        />
      </RuledPanel>
      <RuledPanel
        titleId="g5-bad-debt"
        title={t("accountingG5.badDebt")}
        description={t("accountingG5.badDebtHelp")}
      >
        <KeyedSettings
          area="accounting"
          keys={["accounting.bad_debt_vat_relief"]}
          label={t("accountingG5.badDebt")}
        />
      </RuledPanel>
      {canExport ? <ExportSection connections={all} /> : null}
    </div>
  );
}
