import { ApiError, unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  cn,
  FigureStrip,
  FormPanel,
  figureCell,
  NamePlate,
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
import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { api, usePermission } from "../api";
import { PanelEmpty, PanelLoading } from "../billing/moneyUi";
import { useIsPhone } from "../billing/useIsPhone";

type Scope = components["schemas"]["Scope"];
type Endpoint = components["schemas"]["WebhookEndpoint"];
type Delivery = components["schemas"]["WebhookDelivery"];
type EventType = components["schemas"]["EventType"];

/** Code and payloads: a ruled box on the stock, scrolling sideways inside itself. */
export const codeBlock =
  "relative overflow-x-auto rounded-md border border-border bg-background px-3 py-2.5 font-mono text-xs leading-relaxed";
const quietGhost = "text-muted-foreground";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : String(error ?? "");
}

/** A secret shown once, with a copy button. */
function SecretOnce({ secret, onDone }: { secret: string; onDone: () => void }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <Alert tone="warning" title={t("developer.secretOnceTitle")}>
      <p className="text-sm">{t("developer.secretOnce")}</p>
      <code
        className="mt-2 block rounded-md border border-field bg-surface px-3 py-2 font-mono text-xs break-all"
        data-testid="secret"
      >
        {secret}
      </code>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => {
            void navigator.clipboard?.writeText(secret);
            setCopied(true);
          }}
        >
          {copied ? t("developer.copied") : t("developer.copy")}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          {t("developer.done")}
        </Button>
      </div>
    </Alert>
  );
}

function useScopes() {
  return useQuery({
    queryKey: ["developer-scopes"],
    queryFn: async () => unwrap(await api.GET("/api/v1/developer/scopes")),
    staleTime: 10 * 60_000,
  });
}

function ScopePicker({
  scopes,
  value,
  onChange,
  legend,
}: {
  scopes: Scope[];
  value: string[];
  onChange: (next: string[]) => void;
  legend: string;
}) {
  return (
    <fieldset className="min-w-0 sm:col-span-2 lg:col-span-3">
      <legend className="mb-1 text-sm font-medium">{legend}</legend>
      <div className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
        {scopes.map((scope) => (
          <label key={scope.key} className="flex min-w-0 items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={value.includes(scope.key)}
              onChange={(e) =>
                onChange(
                  e.target.checked ? [...value, scope.key] : value.filter((v) => v !== scope.key),
                )
              }
            />
            <span className="min-w-0">
              {scope.description}
              <code className="block font-mono text-xs text-muted-foreground">{scope.key}</code>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

// --- overview -----------------------------------------------------------------------------------

type Tab = "overview" | "keys" | "webhooks" | "apps" | "sandboxes";

/** Developer settings: API keys, webhooks, OAuth apps and sandboxes (E27). */
export function DeveloperPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("overview");
  return (
    <div>
      <PageHeader
        title={t("developer.title")}
        actions={
          <>
            <Link
              to="/settings/marketplace"
              className={buttonClass({ variant: "secondary", size: "sm" })}
            >
              {t("marketplace.title")}
            </Link>
            <Link
              to="/developer/docs"
              className={buttonClass({ variant: "secondary", size: "sm" })}
            >
              {t("developer.docs.link")}
            </Link>
          </>
        }
      />
      <Tabs
        label={t("developer.title")}
        tabs={[
          { key: "overview", label: t("developer.tabs.overview") },
          { key: "keys", label: t("developer.tabs.keys") },
          { key: "webhooks", label: t("developer.tabs.webhooks") },
          { key: "apps", label: t("developer.tabs.apps") },
          { key: "sandboxes", label: t("developer.tabs.sandboxes") },
        ]}
        value={tab}
        onChange={setTab}
      >
        {tab === "overview" ? <Overview /> : null}
        {tab === "keys" ? <ApiKeys /> : null}
        {tab === "webhooks" ? <Webhooks /> : null}
        {tab === "apps" ? <Apps /> : null}
        {tab === "sandboxes" ? <Sandboxes /> : null}
      </Tabs>
    </div>
  );
}

function Overview() {
  const { t, i18n } = useTranslation();
  const overview = useQuery({
    queryKey: ["developer-overview"],
    queryFn: async () => unwrap(await api.GET("/api/v1/developer/overview")),
  });
  if (!overview.data) {
    return (
      <RuledPanel label={t("developer.tabs.overview")} flush>
        <PanelLoading label={t("grid.loading")} />
      </RuledPanel>
    );
  }
  const o = overview.data;
  const n = new Intl.NumberFormat(i18n.language);
  return (
    <div className="space-y-4">
      {o.sandbox_of ? <Alert tone="info">{t("developer.sandboxBanner")}</Alert> : null}
      {/* One ruled grid: what is set up, then the last day's traffic, its vertical rules
          lining up from row to row. */}
      <FigureStrip
        label={t("developer.tabs.overview")}
        columns={3}
        figures={[
          { key: "keys", label: t("developer.stats.apiKeys"), value: n.format(o.api_keys) },
          {
            key: "apps",
            label: t("developer.stats.connectedApps"),
            value: n.format(o.connected_apps),
          },
          {
            key: "endpoints",
            label: t("developer.stats.endpoints"),
            value: n.format(o.webhook_endpoints),
          },
          {
            key: "deliveries",
            label: t("developer.stats.deliveries"),
            value: n.format(o.deliveries_24h),
          },
          {
            key: "failing",
            label: t("developer.stats.failing"),
            value: n.format(o.failed_24h),
            tone: o.failed_24h > 0 ? "danger" : "default",
          },
        ]}
      />
      <p className="text-sm text-muted-foreground">
        {t("developer.rateLimits", {
          perMinute: o.rate_limit_per_minute,
          perSecond: o.burst_per_second,
        })}
      </p>
    </div>
  );
}

// --- API keys -----------------------------------------------------------------------------------

function ApiKeys() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const phone = useIsPhone();
  const canManage = usePermission("developer.apikey.manage");
  const scopes = useScopes();
  const keys = useQuery({
    queryKey: ["api-keys"],
    queryFn: async () => unwrap(await api.GET("/api/v1/developer/api-keys")),
    enabled: canManage,
  });
  const [secret, setSecret] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [allowlist, setAllowlist] = useState("");
  const [expires, setExpires] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["api-keys"] });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/developer/api-keys", {
          body: {
            name,
            scopes: chosen as components["schemas"]["ApiKeyCreateRequest"]["scopes"],
            ip_allowlist: allowlist
              .split(/[\s,]+/)
              .map((v) => v.trim())
              .filter(Boolean),
            expires_at: expires ? new Date(expires).toISOString() : null,
          },
        }),
      ),
    onSuccess: (key) => {
      setSecret(key.secret);
      setName("");
      setChosen([]);
      refresh();
    },
  });
  const rotate = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/developer/api-keys/{id}/rotate", { params: { path: { id } } }),
      ),
    onSuccess: (key) => {
      setSecret(key.secret);
      refresh();
    },
  });
  const revoke = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/developer/api-keys/{id}/revoke", { params: { path: { id } } }),
      ),
    onSuccess: refresh,
  });
  if (!canManage) return <Alert tone="info">{t("developer.noPermission")}</Alert>;
  const rows = keys.data?.results ?? [];
  const lastUsed = (iso: string | null | undefined) =>
    iso ? formatDateTime(iso, i18n.language) : t("developer.never");
  return (
    <div className="space-y-6">
      {secret ? <SecretOnce secret={secret} onDone={() => setSecret(null)} /> : null}
      <RuledPanel title={t("developer.tabs.keys")} flush>
        <RuledTable
          caption={t("developer.tabs.keys")}
          loading={!keys.data}
          loadingLabel={t("grid.loading")}
          empty={keys.data && rows.length === 0 ? t("developer.keys.none") : undefined}
          columns={[
            { key: "name", header: t("developer.keys.name"), width: "min-w-40" },
            ...(phone
              ? []
              : [
                  { key: "key", header: t("developer.keys.key") },
                  { key: "scopes", header: t("developer.scopes") },
                  { key: "used", header: t("developer.keys.lastUsed") },
                ]),
            { key: "actions", header: t("developer.actions"), hidden: true },
          ]}
        >
          {rows.map((key) => (
            <tr key={key.id}>
              <td>
                <span className={cn("font-medium", !key.active && "text-muted-foreground")}>
                  {key.name}
                </span>
                {!key.active || phone ? (
                  <span className="block text-xs text-muted-foreground">
                    {[
                      key.active ? null : t("developer.keys.inactive"),
                      phone ? key.display : null,
                      phone ? lastUsed(key.last_used_at) : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                ) : null}
              </td>
              {phone ? null : (
                <>
                  <td>
                    <code className="font-mono text-xs whitespace-nowrap">{key.display}</code>
                  </td>
                  <td className="text-xs text-muted-foreground">
                    <code className="font-mono">{key.scopes.join(", ")}</code>
                  </td>
                  <td className="whitespace-nowrap tabular-nums">{lastUsed(key.last_used_at)}</td>
                </>
              )}
              <td className="py-1.5 text-right">
                {key.active ? (
                  <span className="inline-flex flex-wrap justify-end gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() => rotate.mutate(key.id)}
                      aria-label={t("developer.keys.rotateNamed", { name: key.name })}
                    >
                      {t("developer.keys.rotate")}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className={quietGhost}
                      onClick={() => {
                        if (window.confirm(t("developer.keys.confirmRevoke")))
                          revoke.mutate(key.id);
                      }}
                      aria-label={t("developer.keys.revokeNamed", { name: key.name })}
                    >
                      {t("developer.keys.revoke")}
                    </Button>
                  </span>
                ) : null}
              </td>
            </tr>
          ))}
        </RuledTable>
      </RuledPanel>
      <FormPanel
        title={t("developer.keys.new")}
        submit={t("developer.keys.create")}
        columns={3}
        pending={create.isPending}
        disabled={!name || chosen.length === 0}
        onSubmit={() => create.mutate()}
        error={create.error ? <Alert tone="danger">{errorText(create.error)}</Alert> : null}
      >
        <TextField
          label={t("developer.keys.name")}
          value={name}
          required
          onChange={(e) => setName(e.target.value)}
        />
        <TextField
          label={t("developer.keys.allowlist")}
          hint={t("developer.keys.allowlistHint")}
          value={allowlist}
          onChange={(e) => setAllowlist(e.target.value)}
        />
        <TextField
          label={t("developer.keys.expires")}
          type="date"
          value={expires}
          onChange={(e) => setExpires(e.target.value)}
        />
        {scopes.data ? (
          <ScopePicker
            legend={t("developer.scopes")}
            scopes={scopes.data}
            value={chosen}
            onChange={setChosen}
          />
        ) : null}
      </FormPanel>
    </div>
  );
}

// --- webhooks -----------------------------------------------------------------------------------

function useEventTypes() {
  return useQuery({
    queryKey: ["webhook-event-types"],
    queryFn: async () => unwrap(await api.GET("/api/v1/webhook-event-types")),
    staleTime: 10 * 60_000,
  });
}

function eventOptions(types: EventType[]): string[] {
  const aggregates = Array.from(new Set(types.map((e) => e.aggregate))).sort();
  return [...aggregates.map((a) => `${a}.*`), ...types.map((e) => e.key)];
}

function Webhooks() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("developer.webhook.manage");
  const types = useEventTypes();
  const endpoints = useQuery({
    queryKey: ["webhook-endpoints"],
    queryFn: async () => unwrap(await api.GET("/api/v1/webhook-endpoints")),
  });
  const [secret, setSecret] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [picking, setPicking] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["webhook-endpoints"] });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/webhook-endpoints", { body: { url, events, description } })),
    onSuccess: (endpoint) => {
      setSecret(endpoint.secret);
      setUrl("");
      setDescription("");
      setEvents([]);
      refresh();
    },
  });
  const options = types.data ? eventOptions(types.data) : [];
  const rows = endpoints.data?.results ?? [];
  return (
    <div className="space-y-6">
      {secret ? <SecretOnce secret={secret} onDone={() => setSecret(null)} /> : null}
      <RuledPanel title={t("designS9a.endpoints")} flush>
        {!endpoints.data ? (
          <PanelLoading label={t("grid.loading")} />
        ) : rows.length === 0 ? (
          <PanelEmpty>{t("developer.webhooks.none")}</PanelEmpty>
        ) : (
          <PanelRows>
            {rows.map((endpoint) => (
              <EndpointRow
                key={endpoint.id}
                endpoint={endpoint}
                canManage={canManage}
                open={selected === endpoint.id}
                onToggle={() => setSelected(selected === endpoint.id ? null : endpoint.id)}
                onSecret={setSecret}
                onChanged={refresh}
              />
            ))}
          </PanelRows>
        )}
      </RuledPanel>
      {canManage ? (
        <FormPanel
          title={t("developer.webhooks.new")}
          submit={t("developer.webhooks.create")}
          pending={create.isPending}
          disabled={!url || events.length === 0}
          onSubmit={() => create.mutate()}
          error={create.error ? <Alert tone="danger">{errorText(create.error)}</Alert> : null}
        >
          <TextField
            label={t("developer.webhooks.url")}
            hint={t("developer.webhooks.urlHint")}
            type="url"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <TextField
            label={t("developer.webhooks.description")}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <div className="space-y-2 sm:col-span-2">
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-56">
                <SelectField
                  label={t("developer.webhooks.addEvent")}
                  value={picking}
                  onChange={(e) => setPicking(e.target.value)}
                  options={[
                    { value: "", label: t("developer.webhooks.chooseEvent") },
                    ...options.map((o) => ({
                      value: o,
                      label: o === "*" ? t("designS9a.allEvents") : o,
                    })),
                  ]}
                />
              </div>
              <Button
                type="button"
                variant="secondary"
                disabled={!picking || events.includes(picking)}
                onClick={() => {
                  setEvents([...events, picking]);
                  setPicking("");
                }}
              >
                {t("developer.webhooks.add")}
              </Button>
            </div>
            {events.length ? (
              <ul aria-label={t("developer.webhooks.events")} className="flex flex-wrap gap-2">
                {events.map((ev) => (
                  <li
                    key={ev}
                    className={cn(
                      "flex h-8 items-center gap-1 rounded-md border border-border bg-surface pl-2.5 text-xs",
                      ev !== "*" && "font-mono",
                    )}
                  >
                    {ev === "*" ? t("designS9a.allEvents") : ev}
                    <button
                      type="button"
                      className="grid size-8 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                      aria-label={t("developer.webhooks.removeEvent", {
                        event: ev === "*" ? t("designS9a.allEvents") : ev,
                      })}
                      onClick={() => setEvents(events.filter((x) => x !== ev))}
                    >
                      <X aria-hidden="true" className="size-3.5" strokeWidth={1.75} />
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </FormPanel>
      ) : null}
    </div>
  );
}

function EndpointRow({
  endpoint,
  canManage,
  open,
  onToggle,
  onSecret,
  onChanged,
}: {
  endpoint: Endpoint;
  canManage: boolean;
  open: boolean;
  onToggle: () => void;
  onSecret: (s: string) => void;
  onChanged: () => void;
}) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const path = { params: { path: { id: endpoint.id } } };
  const test = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/webhook-endpoints/{id}/test", path)),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["webhook-deliveries"] }),
  });
  const toggle = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/webhook-endpoints/{id}", {
          ...path,
          body: { status: endpoint.status === "active" ? "paused" : "active" },
        }),
      ),
    onSuccess: onChanged,
  });
  const rotate = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/webhook-endpoints/{id}/rotate-secret", path)),
    onSuccess: (r) => {
      onSecret(r.secret);
      onChanged();
    },
  });
  const remove = useMutation({
    mutationFn: async () => {
      await api.DELETE("/api/v1/webhook-endpoints/{id}", path);
    },
    onSuccess: onChanged,
  });
  const status = endpoint.status;
  return (
    <PanelRow className="space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <p className="font-medium break-all">{endpoint.url}</p>
          <p className="text-xs text-muted-foreground">
            <span
              className={cn(
                status === "disabled" && "font-medium text-danger",
                status === "paused" && "text-muted-foreground",
              )}
            >
              {t(`developer.webhooks.status.${status}`)}
            </span>
            {" · "}
            {endpoint.events.includes("*") ? (
              t("designS9a.allEvents")
            ) : (
              <code className="font-mono">{endpoint.events.join(", ")}</code>
            )}
            {endpoint.failing_since ? (
              <span className="font-medium text-danger">
                {" · "}
                {t("developer.webhooks.failingSince", {
                  when: formatDateTime(endpoint.failing_since, i18n.language),
                })}
              </span>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={onToggle}
            aria-expanded={open}
          >
            {t("developer.webhooks.log")}
          </Button>
          {canManage ? (
            <>
              <Button type="button" size="sm" variant="secondary" onClick={() => test.mutate()}>
                {t("developer.webhooks.sendTest")}
              </Button>
              <Button type="button" size="sm" variant="secondary" onClick={() => toggle.mutate()}>
                {status === "active"
                  ? t("developer.webhooks.pause")
                  : t("developer.webhooks.enable")}
              </Button>
              <Button type="button" size="sm" variant="secondary" onClick={() => rotate.mutate()}>
                {t("developer.webhooks.rotate")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className={quietGhost}
                onClick={() => {
                  if (window.confirm(t("developer.webhooks.confirmDelete"))) remove.mutate();
                }}
              >
                {t("developer.webhooks.delete")}
              </Button>
            </>
          ) : null}
        </div>
      </div>
      {test.isSuccess ? (
        <p role="status" className="text-xs text-success">
          {t("developer.webhooks.testQueued")}
        </p>
      ) : null}
      {open ? <DeliveryLog endpointId={endpoint.id} canManage={canManage} /> : null}
    </PanelRow>
  );
}

function DeliveryLog({ endpointId, canManage }: { endpointId: string; canManage: boolean }) {
  const { t, i18n } = useTranslation();
  const phone = useIsPhone();
  const [open, setOpen] = useState<string | null>(null);
  const deliveries = useQuery({
    queryKey: ["webhook-deliveries", endpointId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/webhook-deliveries", {
          params: { query: { endpoint: endpointId } },
        }),
      ),
  });
  const rows = deliveries.data?.results ?? [];
  return (
    <RuledTable
      caption={t("developer.webhooks.log")}
      // Flush under the endpoint: the log's rules run the panel's full width, not a box.
      className="-mx-5 -mb-2.5 border-t border-rule"
      loading={!deliveries.data}
      loadingLabel={t("grid.loading")}
      empty={deliveries.data && rows.length === 0 ? t("developer.deliveries.none") : undefined}
      columns={[
        { key: "event", header: t("developer.deliveries.event"), width: "min-w-36" },
        { key: "status", header: t("developer.deliveries.status") },
        ...(phone
          ? []
          : [
              { key: "attempts", header: t("developer.deliveries.attempts"), end: true },
              { key: "when", header: t("developer.deliveries.when") },
              { key: "actions", header: t("developer.actions"), hidden: true },
            ]),
      ]}
    >
      {rows.map((d) => (
        <DeliveryRow
          key={d.id}
          delivery={d}
          canManage={canManage}
          open={open === d.id}
          onToggle={() => setOpen(open === d.id ? null : d.id)}
          locale={i18n.language}
          phone={phone}
        />
      ))}
    </RuledTable>
  );
}

function DeliveryRow({
  delivery,
  canManage,
  open,
  onToggle,
  locale,
  phone,
}: {
  delivery: Delivery;
  canManage: boolean;
  open: boolean;
  onToggle: () => void;
  locale: string;
  phone: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const path = { params: { path: { id: delivery.id } } };
  const detail = useQuery({
    queryKey: ["webhook-delivery", delivery.id],
    queryFn: async () => unwrap(await api.GET("/api/v1/webhook-deliveries/{id}", path)),
    enabled: open,
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["webhook-deliveries"] });
  const redeliver = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/webhook-deliveries/{id}/redeliver", path)),
    onSuccess: refresh,
  });
  const retry = useMutation({
    mutationFn: async () => {
      await api.POST("/api/v1/webhook-deliveries/{id}/retry-now", path);
    },
    onSuccess: refresh,
  });
  const waiting = delivery.status === "pending" || delivery.status === "retrying";
  const columns = phone ? 2 : 5;
  const action = canManage ? (
    <Button
      type="button"
      size="sm"
      variant="secondary"
      onClick={() => (waiting ? retry.mutate() : redeliver.mutate())}
    >
      {waiting ? t("developer.deliveries.retryNow") : t("developer.deliveries.redeliver")}
    </Button>
  ) : null;
  return (
    <>
      <tr>
        <td>
          <button
            type="button"
            className="inline-flex items-center gap-1 text-left font-mono text-xs text-link hover:underline"
            onClick={onToggle}
            aria-expanded={open}
          >
            {delivery.event_type}
          </button>
          {phone ? (
            <>
              <span className="block text-xs text-muted-foreground tabular-nums">
                {formatDateTime(delivery.created_at, locale)}
              </span>
              {action ? <span className="mt-2 block">{action}</span> : null}
            </>
          ) : null}
        </td>
        <td>
          <span className={delivery.status === "failed" ? "font-medium text-danger" : undefined}>
            {t(`developer.deliveries.statuses.${delivery.status}`)}
          </span>
          {delivery.last_status_code ? (
            <span className="text-muted-foreground tabular-nums">
              {" "}
              ({delivery.last_status_code})
            </span>
          ) : null}
        </td>
        {phone ? null : (
          <>
            <td className={figureCell}>{delivery.attempt_count}</td>
            <td className="whitespace-nowrap tabular-nums">
              {formatDateTime(delivery.created_at, locale)}
            </td>
            <td className="py-1.5 text-right whitespace-nowrap">{action}</td>
          </>
        )}
      </tr>
      {open ? (
        <tr>
          <td colSpan={columns} className="space-y-3 bg-background/60">
            {!detail.data ? (
              <PanelLoading label={t("grid.loading")} />
            ) : (
              <>
                <ol className="space-y-2" aria-label={t("developer.deliveries.attempts")}>
                  {detail.data.attempts.map((a) => (
                    <li key={a.number} className="text-sm">
                      <p className="tabular-nums">
                        <span className="font-medium">#{a.number}</span> ·{" "}
                        {formatDateTime(a.attempted_at, locale)} ·{" "}
                        <span
                          className={
                            a.error || (a.status_code ?? 0) >= 400 ? "text-danger" : undefined
                          }
                        >
                          {a.status_code ?? a.error}
                        </span>{" "}
                        · {a.duration_ms} ms
                      </p>
                      {a.response_snippet ? (
                        <pre className={cn(codeBlock, "mt-1")}>{a.response_snippet}</pre>
                      ) : null}
                    </li>
                  ))}
                </ol>
                <div>
                  <p className="mb-1 text-xs font-semibold text-muted-foreground">
                    {t("developer.deliveries.payload")}
                  </p>
                  <pre
                    className={codeBlock}
                    tabIndex={0}
                    aria-label={t("developer.deliveries.payload")}
                  >
                    {JSON.stringify(detail.data.body, null, 2)}
                  </pre>
                </div>
              </>
            )}
          </td>
        </tr>
      ) : null}
    </>
  );
}

// --- OAuth apps and connected apps --------------------------------------------------------------

function Apps() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canRegister = usePermission("developer.app.manage");
  const canConnect = usePermission("developer.app.connect");
  const scopes = useScopes();
  const apps = useQuery({
    queryKey: ["oauth-apps"],
    queryFn: async () => unwrap(await api.GET("/api/v1/developer/oauth-apps")),
    enabled: canRegister,
  });
  const connected = useQuery({
    queryKey: ["connected-apps"],
    queryFn: async () => unwrap(await api.GET("/api/v1/developer/connected-apps")),
    enabled: canConnect,
  });
  const [secret, setSecret] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [redirect, setRedirect] = useState("");
  const [allowed, setAllowed] = useState<string[]>([]);
  const [confidential, setConfidential] = useState(true);
  const register = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/developer/oauth-apps", {
          body: {
            name,
            description: "",
            redirect_uris: redirect.split(/\s+/).filter(Boolean),
            allowed_scopes:
              allowed as components["schemas"]["OAuthApplicationWriteRequest"]["allowed_scopes"],
            confidential,
          },
        }),
      ),
    onSuccess: (app) => {
      setSecret(app.client_secret ?? null);
      setName("");
      setRedirect("");
      setAllowed([]);
      void queryClient.invalidateQueries({ queryKey: ["oauth-apps"] });
    },
  });
  const disconnect = useMutation({
    mutationFn: async (id: string) => {
      await api.POST("/api/v1/developer/connected-apps/{id}/revoke", {
        params: { path: { id } },
      });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["connected-apps"] }),
  });
  const grants = connected.data?.results ?? [];
  const registered = apps.data?.results ?? [];
  return (
    <div className="space-y-6">
      {secret ? <SecretOnce secret={secret} onDone={() => setSecret(null)} /> : null}
      {canConnect ? (
        <RuledPanel title={t("developer.apps.connected")} flush>
          {!connected.data ? (
            <PanelLoading label={t("grid.loading")} />
          ) : grants.length === 0 ? (
            <PanelEmpty>{t("developer.apps.noneConnected")}</PanelEmpty>
          ) : (
            <PanelRows>
              {grants.map((grant) => (
                <PanelRow key={grant.id}>
                  <NamePlate
                    name={grant.application.name}
                    context={
                      <>
                        {grant.user_email} ·{" "}
                        <code className="font-mono">{grant.scopes.join(", ")}</code> ·{" "}
                        <span className="tabular-nums">
                          {grant.last_used_at
                            ? formatDateTime(grant.last_used_at, i18n.language)
                            : t("developer.never")}
                        </span>
                      </>
                    }
                    aside={
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className={quietGhost}
                        onClick={() => disconnect.mutate(grant.id)}
                        aria-label={t("developer.apps.disconnectNamed", {
                          name: grant.application.name,
                        })}
                      >
                        {t("developer.apps.disconnect")}
                      </Button>
                    }
                  />
                </PanelRow>
              ))}
            </PanelRows>
          )}
        </RuledPanel>
      ) : null}
      {canRegister ? (
        <>
          <RuledPanel title={t("developer.apps.registered")} flush>
            {!apps.data ? (
              <PanelLoading label={t("grid.loading")} />
            ) : registered.length === 0 ? (
              <PanelEmpty>{t("designS9a.noApps")}</PanelEmpty>
            ) : (
              <PanelRows>
                {registered.map((app) => (
                  <PanelRow key={app.id}>
                    <NamePlate
                      name={app.name}
                      context={<code className="font-mono">{app.client_id}</code>}
                    />
                  </PanelRow>
                ))}
              </PanelRows>
            )}
          </RuledPanel>
          <FormPanel
            title={t("designS9a.registerApp")}
            submit={t("developer.apps.register")}
            columns={2}
            pending={register.isPending}
            disabled={!name || !redirect || allowed.length === 0}
            onSubmit={() => register.mutate()}
            error={register.error ? <Alert tone="danger">{errorText(register.error)}</Alert> : null}
          >
            <TextField
              label={t("developer.apps.name")}
              value={name}
              required
              onChange={(e) => setName(e.target.value)}
            />
            <TextField
              label={t("developer.apps.redirects")}
              hint={t("developer.apps.redirectsHint")}
              value={redirect}
              required
              onChange={(e) => setRedirect(e.target.value)}
            />
            <label className="flex items-start gap-2 text-sm sm:col-span-2">
              <input
                type="checkbox"
                className="mt-1"
                checked={confidential}
                onChange={(e) => setConfidential(e.target.checked)}
              />
              {t("developer.apps.confidential")}
            </label>
            {scopes.data ? (
              <ScopePicker
                legend={t("developer.apps.allowedScopes")}
                scopes={scopes.data}
                value={allowed}
                onChange={setAllowed}
              />
            ) : null}
          </FormPanel>
        </>
      ) : null}
    </div>
  );
}

// --- sandboxes ----------------------------------------------------------------------------------

function Sandboxes() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("developer.sandbox.manage");
  const sandboxes = useQuery({
    queryKey: ["sandboxes"],
    queryFn: async () => unwrap(await api.GET("/api/v1/developer/sandboxes")),
    enabled: canManage,
  });
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/developer/sandboxes")),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["sandboxes"] }),
  });
  if (!canManage) return <Alert tone="info">{t("developer.noPermission")}</Alert>;
  const rows = sandboxes.data?.results ?? [];
  return (
    <RuledPanel
      title={t("developer.tabs.sandboxes")}
      description={t("developer.sandboxes.intro")}
      flush
      footer={
        <>
          <Button
            type="button"
            size="sm"
            onClick={() => create.mutate()}
            loading={create.isPending}
          >
            {create.isPending ? t("developer.sandboxes.creating") : t("developer.sandboxes.create")}
          </Button>
        </>
      }
    >
      {create.error ? (
        <div className="px-5 pt-4">
          <Alert tone="danger">{errorText(create.error)}</Alert>
        </div>
      ) : null}
      {!sandboxes.data ? (
        <PanelLoading label={t("grid.loading")} />
      ) : rows.length === 0 ? (
        <PanelEmpty>{t("designS9a.noSandboxes")}</PanelEmpty>
      ) : (
        <PanelRows>
          {rows.map((sb) => (
            <PanelRow key={sb.id}>
              <NamePlate
                name={sb.name}
                context={
                  <span className="tabular-nums">
                    {formatDateTime(sb.created_at, i18n.language)}
                  </span>
                }
                aside={
                  <a href={sb.url} className={buttonClass({ variant: "secondary", size: "sm" })}>
                    {t("developer.sandboxes.open")}
                  </a>
                }
              />
            </PanelRow>
          ))}
        </PanelRows>
      )}
    </RuledPanel>
  );
}

/** A guide or reference section on the developer docs page. */
export function DocPanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <RuledPanel title={title} bodyClassName="space-y-3 px-5 py-4 text-sm">
      {children}
    </RuledPanel>
  );
}
