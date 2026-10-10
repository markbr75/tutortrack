import { ApiError, unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type FormEvent, type ReactNode } from "react";

import { api, usePermission } from "../api";

type Scope = components["schemas"]["Scope"];
type Endpoint = components["schemas"]["WebhookEndpoint"];
type Delivery = components["schemas"]["WebhookDelivery"];
type EventType = components["schemas"]["EventType"];

const linkClass = "underline underline-offset-2";
const pre = "overflow-x-auto rounded-md bg-muted p-3 text-xs";

export function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="space-y-3 rounded-lg border border-border p-4">
      <h2 className="font-semibold">{title}</h2>
      {children}
    </section>
  );
}

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
      <code className="mt-2 block break-all rounded bg-muted p-2 text-xs" data-testid="secret">
        {secret}
      </code>
      <div className="mt-2 flex gap-2">
        <Button
          type="button"
          variant="secondary"
          onClick={() => {
            void navigator.clipboard?.writeText(secret);
            setCopied(true);
          }}
        >
          {copied ? t("developer.copied") : t("developer.copy")}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
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
    <fieldset className="space-y-1">
      <legend className="text-sm font-medium">{legend}</legend>
      <div className="grid gap-1 sm:grid-cols-2">
        {scopes.map((scope) => (
          <label key={scope.key} className="flex items-start gap-2 text-sm">
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
            <span>
              <code className="text-xs">{scope.key}</code> {scope.description}
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
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t("developer.title")}</h1>
        <span className="flex gap-4 text-sm">
          <Link to="/developer/docs" className={linkClass}>
            {t("developer.docs.link")}
          </Link>
          <Link to="/settings/marketplace" className={linkClass}>
            {t("marketplace.title")}
          </Link>
        </span>
      </div>
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
  const { t } = useTranslation();
  const overview = useQuery({
    queryKey: ["developer-overview"],
    queryFn: async () => unwrap(await api.GET("/api/v1/developer/overview")),
  });
  if (!overview.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const o = overview.data;
  const stats: [string, number][] = [
    [t("developer.stats.apiKeys"), o.api_keys],
    [t("developer.stats.connectedApps"), o.connected_apps],
    [t("developer.stats.endpoints"), o.webhook_endpoints],
    [t("developer.stats.deliveries"), o.deliveries_24h],
    [t("developer.stats.failing"), o.failed_24h],
  ];
  return (
    <div className="space-y-4">
      {o.sandbox_of ? <Alert tone="info">{t("developer.sandboxBanner")}</Alert> : null}
      <dl className="grid gap-3 sm:grid-cols-5">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-border p-3">
            <dt className="text-sm text-muted-foreground">{label}</dt>
            <dd className="text-2xl font-semibold">{value}</dd>
          </div>
        ))}
      </dl>
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
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <div className="space-y-4">
      {secret ? <SecretOnce secret={secret} onDone={() => setSecret(null)} /> : null}
      <Card title={t("developer.keys.new")}>
        <form onSubmit={submit} className="space-y-3">
          <TextField
            label={t("developer.keys.name")}
            value={name}
            required
            onChange={(e) => setName(e.target.value)}
          />
          {scopes.data ? (
            <ScopePicker
              legend={t("developer.scopes")}
              scopes={scopes.data}
              value={chosen}
              onChange={setChosen}
            />
          ) : null}
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
          {create.error ? <Alert tone="danger">{errorText(create.error)}</Alert> : null}
          <Button type="submit" disabled={!name || chosen.length === 0 || create.isPending}>
            {t("developer.keys.create")}
          </Button>
        </form>
      </Card>
      {!keys.data ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : keys.data.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("developer.keys.none")}</p>
      ) : (
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{t("developer.tabs.keys")}</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="py-2">
                {t("developer.keys.name")}
              </th>
              <th scope="col">{t("developer.keys.key")}</th>
              <th scope="col">{t("developer.scopes")}</th>
              <th scope="col">{t("developer.keys.lastUsed")}</th>
              <th scope="col">
                <span className="sr-only">{t("developer.actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {keys.data.results.map((key) => (
              <tr key={key.id} className="border-b border-border align-top">
                <td className="py-2">
                  {key.name}
                  {!key.active ? (
                    <span className="ml-2 text-xs text-muted-foreground">
                      ({t("developer.keys.inactive")})
                    </span>
                  ) : null}
                </td>
                <td>
                  <code className="text-xs">{key.display}</code>
                </td>
                <td className="text-xs">{key.scopes.join(", ")}</td>
                <td>
                  {key.last_used_at
                    ? formatDateTime(key.last_used_at, i18n.language)
                    : t("developer.never")}
                </td>
                <td className="space-x-2 whitespace-nowrap text-right">
                  {key.active ? (
                    <>
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => rotate.mutate(key.id)}
                        aria-label={t("developer.keys.rotateNamed", { name: key.name })}
                      >
                        {t("developer.keys.rotate")}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={() => {
                          if (window.confirm(t("developer.keys.confirmRevoke")))
                            revoke.mutate(key.id);
                        }}
                        aria-label={t("developer.keys.revokeNamed", { name: key.name })}
                      >
                        {t("developer.keys.revoke")}
                      </Button>
                    </>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
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
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  const options = types.data ? eventOptions(types.data) : [];
  return (
    <div className="space-y-4">
      {secret ? <SecretOnce secret={secret} onDone={() => setSecret(null)} /> : null}
      {canManage ? (
        <Card title={t("developer.webhooks.new")}>
          <form onSubmit={submit} className="space-y-3">
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
            <div className="flex flex-wrap items-end gap-2">
              <SelectField
                label={t("developer.webhooks.addEvent")}
                value={picking}
                onChange={(e) => setPicking(e.target.value)}
                options={[
                  { value: "", label: t("developer.webhooks.chooseEvent") },
                  ...options.map((o) => ({ value: o, label: o })),
                ]}
              />
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
                  <li key={ev} className="rounded bg-muted px-2 py-1 text-xs">
                    {ev}{" "}
                    <button
                      type="button"
                      className="ml-1"
                      aria-label={t("developer.webhooks.removeEvent", { event: ev })}
                      onClick={() => setEvents(events.filter((x) => x !== ev))}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            {create.error ? <Alert tone="danger">{errorText(create.error)}</Alert> : null}
            <Button type="submit" disabled={!url || events.length === 0 || create.isPending}>
              {t("developer.webhooks.create")}
            </Button>
          </form>
        </Card>
      ) : null}
      {!endpoints.data ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : endpoints.data.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("developer.webhooks.none")}</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {endpoints.data.results.map((endpoint) => (
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
        </ul>
      )}
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
  return (
    <li className="space-y-2 p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0">
          <span className="block break-all font-medium">{endpoint.url}</span>
          <span className="text-xs text-muted-foreground">
            {t(`developer.webhooks.status.${endpoint.status}`)} · {endpoint.events.join(", ")}
            {endpoint.failing_since
              ? ` · ${t("developer.webhooks.failingSince", {
                  when: formatDateTime(endpoint.failing_since, i18n.language),
                })}`
              : ""}
          </span>
        </span>
        <span className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" onClick={onToggle} aria-expanded={open}>
            {t("developer.webhooks.log")}
          </Button>
          {canManage ? (
            <>
              <Button type="button" variant="secondary" onClick={() => test.mutate()}>
                {t("developer.webhooks.sendTest")}
              </Button>
              <Button type="button" variant="secondary" onClick={() => toggle.mutate()}>
                {endpoint.status === "active"
                  ? t("developer.webhooks.pause")
                  : t("developer.webhooks.enable")}
              </Button>
              <Button type="button" variant="ghost" onClick={() => rotate.mutate()}>
                {t("developer.webhooks.rotate")}
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  if (window.confirm(t("developer.webhooks.confirmDelete"))) remove.mutate();
                }}
              >
                {t("developer.webhooks.delete")}
              </Button>
            </>
          ) : null}
        </span>
      </div>
      {test.isSuccess ? (
        <p role="status" className="text-xs text-muted-foreground">
          {t("developer.webhooks.testQueued")}
        </p>
      ) : null}
      {open ? <DeliveryLog endpointId={endpoint.id} canManage={canManage} /> : null}
    </li>
  );
}

function DeliveryLog({ endpointId, canManage }: { endpointId: string; canManage: boolean }) {
  const { t, i18n } = useTranslation();
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
  if (!deliveries.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  if (deliveries.data.results.length === 0)
    return <p className="text-xs text-muted-foreground">{t("developer.deliveries.none")}</p>;
  return (
    <table className="w-full text-left text-xs">
      <caption className="sr-only">{t("developer.webhooks.log")}</caption>
      <thead>
        <tr className="border-b border-border">
          <th scope="col" className="py-1">
            {t("developer.deliveries.event")}
          </th>
          <th scope="col">{t("developer.deliveries.status")}</th>
          <th scope="col">{t("developer.deliveries.attempts")}</th>
          <th scope="col">{t("developer.deliveries.when")}</th>
          <th scope="col">
            <span className="sr-only">{t("developer.actions")}</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {deliveries.data.results.map((d) => (
          <DeliveryRow
            key={d.id}
            delivery={d}
            canManage={canManage}
            open={open === d.id}
            onToggle={() => setOpen(open === d.id ? null : d.id)}
            locale={i18n.language}
          />
        ))}
      </tbody>
    </table>
  );
}

function DeliveryRow({
  delivery,
  canManage,
  open,
  onToggle,
  locale,
}: {
  delivery: Delivery;
  canManage: boolean;
  open: boolean;
  onToggle: () => void;
  locale: string;
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
  return (
    <>
      <tr className="border-b border-border">
        <td className="py-1">
          <button type="button" className={linkClass} onClick={onToggle} aria-expanded={open}>
            {delivery.event_type}
          </button>
        </td>
        <td>
          {t(`developer.deliveries.statuses.${delivery.status}`)}
          {delivery.last_status_code ? ` (${delivery.last_status_code})` : ""}
        </td>
        <td>{delivery.attempt_count}</td>
        <td>{formatDateTime(delivery.created_at, locale)}</td>
        <td className="space-x-2 whitespace-nowrap text-right">
          {canManage && waiting ? (
            <Button type="button" variant="ghost" onClick={() => retry.mutate()}>
              {t("developer.deliveries.retryNow")}
            </Button>
          ) : null}
          {canManage && !waiting ? (
            <Button type="button" variant="ghost" onClick={() => redeliver.mutate()}>
              {t("developer.deliveries.redeliver")}
            </Button>
          ) : null}
        </td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={5} className="space-y-2 py-2">
            {!detail.data ? (
              <Spinner className="size-4" label={t("grid.loading")} />
            ) : (
              <>
                <ol className="space-y-1" aria-label={t("developer.deliveries.attempts")}>
                  {detail.data.attempts.map((a) => (
                    <li key={a.number}>
                      #{a.number} · {formatDateTime(a.attempted_at, locale)} ·{" "}
                      {a.status_code ?? a.error} · {a.duration_ms} ms
                      {a.response_snippet ? <pre className={pre}>{a.response_snippet}</pre> : null}
                    </li>
                  ))}
                </ol>
                <pre className={pre} aria-label={t("developer.deliveries.payload")}>
                  {JSON.stringify(detail.data.body, null, 2)}
                </pre>
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
  return (
    <div className="space-y-4">
      {canConnect ? (
        <Card title={t("developer.apps.connected")}>
          {!connected.data ? (
            <Spinner className="size-5" label={t("grid.loading")} />
          ) : connected.data.results.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("developer.apps.noneConnected")}</p>
          ) : (
            <ul className="divide-y divide-border">
              {connected.data.results.map((grant) => (
                <li key={grant.id} className="flex flex-wrap justify-between gap-2 py-2 text-sm">
                  <span>
                    <span className="font-medium">{grant.application.name}</span>{" "}
                    <span className="text-xs text-muted-foreground">
                      {grant.user_email} · {grant.scopes.join(", ")} ·{" "}
                      {grant.last_used_at
                        ? formatDateTime(grant.last_used_at, i18n.language)
                        : t("developer.never")}
                    </span>
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => disconnect.mutate(grant.id)}
                    aria-label={t("developer.apps.disconnectNamed", {
                      name: grant.application.name,
                    })}
                  >
                    {t("developer.apps.disconnect")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : null}
      {canRegister ? (
        <Card title={t("developer.apps.registered")}>
          {secret ? <SecretOnce secret={secret} onDone={() => setSecret(null)} /> : null}
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              register.mutate();
            }}
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
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
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
            {register.error ? <Alert tone="danger">{errorText(register.error)}</Alert> : null}
            <Button type="submit" disabled={!name || !redirect || allowed.length === 0}>
              {t("developer.apps.register")}
            </Button>
          </form>
          {apps.data && apps.data.results.length ? (
            <ul className="divide-y divide-border text-sm">
              {apps.data.results.map((app) => (
                <li key={app.id} className="py-2">
                  <span className="font-medium">{app.name}</span>{" "}
                  <code className="text-xs">{app.client_id}</code>
                </li>
              ))}
            </ul>
          ) : null}
        </Card>
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
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{t("developer.sandboxes.intro")}</p>
      {create.error ? <Alert tone="danger">{errorText(create.error)}</Alert> : null}
      <Button type="button" onClick={() => create.mutate()} disabled={create.isPending}>
        {create.isPending ? t("developer.sandboxes.creating") : t("developer.sandboxes.create")}
      </Button>
      {sandboxes.data?.results.length ? (
        <ul className="divide-y divide-border rounded-lg border border-border text-sm">
          {sandboxes.data.results.map((sb) => (
            <li key={sb.id} className="flex flex-wrap justify-between gap-2 p-3">
              <span>
                <span className="font-medium">{sb.name}</span>{" "}
                <span className="text-xs text-muted-foreground">
                  {formatDateTime(sb.created_at, i18n.language)}
                </span>
              </span>
              <a href={sb.url} className={linkClass}>
                {t("developer.sandboxes.open")}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
