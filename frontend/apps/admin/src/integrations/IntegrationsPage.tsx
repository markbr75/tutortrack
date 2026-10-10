import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, useMe, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";

type Connection = components["schemas"]["IntegrationConnection"];
type Provider = components["schemas"]["Provider"];
type Level = "user" | "organisation";

const VIDEO = ["none", "builtin", "zoom", "teams", "google_meet", "lessonspace"] as const;
const RETURN_PATH = "/settings/integrations";

/** Finishes an OAuth connection when the provider sends the browser back here with
 * `?code&state` (E22-T01), then tidies the URL. */
function useOAuthCompletion(onDone: () => void) {
  const started = useRef(false);
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  const state = params.get("state");
  const denied = params.get("integration_error");
  const complete = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/integrations/oauth/complete", {
          body: { code: code ?? "", state: state ?? "" },
        }),
      ),
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

function useConnections(mine: boolean) {
  return useQuery({
    queryKey: ["integrations", "connections", mine],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/integrations/connections", {
          params: { query: mine ? { mine: true } : {} },
        }),
      ).results,
  });
}

function StatusText({ connection }: { connection: Connection }) {
  const { t, i18n } = useTranslation();
  return (
    <p className="text-sm">
      <span
        className={
          connection.status === "active" ? "font-medium text-success" : "font-medium text-danger"
        }
      >
        {t(`integrations.status.${connection.status}`)}
      </span>
      {connection.account_name ? ` · ${connection.account_name}` : ""}
      {connection.last_sync_at
        ? ` · ${t("integrations.lastSync", { when: formatDateTime(connection.last_sync_at, i18n.language) })}`
        : ""}
    </p>
  );
}

/** Which calendars count as busy, where lessons go, two-way edits and the title. */
export function CalendarSyncPanel({ connectionId }: { connectionId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const path = { params: { path: { id: connectionId } } };
  const page = useQuery({
    queryKey: ["calendar-sync", connectionId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/calendar-sync/connections/{id}/settings", path)),
  });
  const [read, setRead] = useState<string[]>([]);
  const [write, setWrite] = useState("");
  const [writeEnabled, setWriteEnabled] = useState(true);
  const [twoWay, setTwoWay] = useState(false);
  const [title, setTitle] = useState("");
  useEffect(() => {
    if (!page.data) return;
    const s = page.data.settings;
    setRead(s.read_calendar_ids as string[]);
    setWrite(s.write_calendar_id ?? "");
    setWriteEnabled(s.write_enabled ?? true);
    setTwoWay(s.two_way ?? false);
    setTitle(s.title_format ?? "");
  }, [page.data]);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/calendar-sync/connections/{id}/settings", {
          ...path,
          body: {
            read_calendar_ids: read,
            write_calendar_id: write,
            write_enabled: writeEnabled,
            two_way: twoWay,
            title_format: title,
          },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["calendar-sync", connectionId], data),
  });
  const syncNow = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/calendar-sync/connections/{id}/sync", path)),
  });
  if (page.isPending) return <Spinner className="size-4" label={t("grid.loading")} />;
  if (!page.data) return <ErrorList error={page.error} />;
  const calendars = page.data.calendars;
  return (
    <form
      className="mt-3 space-y-3 border-t border-border pt-3"
      aria-label={t("integrations.syncSettings")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {page.data.calendars_error ? <Alert tone="warning">{page.data.calendars_error}</Alert> : null}
      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">{t("integrations.readCalendars")}</legend>
        <p className="text-xs text-muted-foreground">{t("integrations.readHelp")}</p>
        {calendars.map((c) => (
          <label key={c.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={read.includes(c.id)}
              onChange={(e) =>
                setRead(e.target.checked ? [...read, c.id] : read.filter((id) => id !== c.id))
              }
            />
            {c.name}
          </label>
        ))}
      </fieldset>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={writeEnabled}
          onChange={(e) => setWriteEnabled(e.target.checked)}
        />
        {t("integrations.writeEnabled")}
      </label>
      {writeEnabled ? (
        <SelectField
          label={t("integrations.writeCalendar")}
          value={write}
          onChange={(e) => setWrite(e.target.value)}
          options={[
            { value: "", label: t("integrations.ownCalendar") },
            ...calendars.filter((c) => c.writable).map((c) => ({ value: c.id, label: c.name })),
          ]}
        />
      ) : null}
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={twoWay}
          disabled={!page.data.two_way_allowed}
          onChange={(e) => setTwoWay(e.target.checked)}
        />
        {t("integrations.twoWay")}
      </label>
      <p className="text-xs text-muted-foreground">{t("integrations.twoWayHelp")}</p>
      <TextField
        label={t("integrations.titleFormat")}
        hint={t("integrations.titleHelp")}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" type="submit" disabled={save.isPending}>
          {t("common.save")}
        </Button>
        <Button size="sm" variant="secondary" type="button" onClick={() => syncNow.mutate()}>
          {t("integrations.syncNow")}
        </Button>
      </div>
      {save.isSuccess ? <p role="status">{t("integrations.saved")}</p> : null}
      <ErrorList error={save.error ?? syncNow.error} />
    </form>
  );
}

function ConnectionCard({ connection, showOwner }: { connection: Connection; showOwner: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const me = useMe();
  const [open, setOpen] = useState(false);
  const path = { params: { path: { id: connection.id } } };
  const act = useMutation({
    mutationFn: async (kind: "check" | "disconnect") =>
      kind === "check"
        ? unwrap(await api.POST("/api/v1/integrations/connections/{id}/check", path))
        : unwrap(await api.POST("/api/v1/integrations/connections/{id}/disconnect", path)),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["integrations"] }),
  });
  const mine = connection.user?.id === me.data?.user.id;
  const calendar = connection.capabilities.includes("calendar") && connection.level === "user";
  return (
    <li className="rounded-md border border-border p-4" aria-label={connection.provider_name}>
      <h3 className="font-semibold">{connection.provider_name}</h3>
      {showOwner ? (
        <p className="text-sm text-muted-foreground">
          {connection.user ? connection.user.name : t("integrations.organisationLevel")}
        </p>
      ) : null}
      <StatusText connection={connection} />
      {connection.error ? (
        <Alert tone={connection.status === "needs_reconnect" ? "danger" : "warning"}>
          {connection.status === "needs_reconnect" ? t("integrations.reconnectNeeded") : null}{" "}
          {connection.error}
        </Alert>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-2">
        {calendar && mine ? (
          <Button size="sm" variant="secondary" onClick={() => setOpen(!open)} aria-expanded={open}>
            {t("integrations.syncSettings")}
          </Button>
        ) : null}
        <Button size="sm" variant="secondary" onClick={() => act.mutate("check")}>
          {t("integrations.check")}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => act.mutate("disconnect")}>
          {t("integrations.disconnect")}
        </Button>
      </div>
      <ErrorList error={act.error} />
      {open ? <CalendarSyncPanel connectionId={connection.id} /> : null}
    </li>
  );
}

/** Connect buttons (OAuth) and credential forms (CalDAV, API keys) for one level. */
export function ConnectProviders({
  level,
  providers,
  returnPath,
}: {
  level: Level;
  providers: Provider[];
  returnPath: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const start = useMutation({
    mutationFn: async (provider: string) =>
      unwrap(
        await api.POST("/api/v1/integrations/oauth/start", {
          body: { provider, level, next: returnPath },
        }),
      ),
    onSuccess: (result) => window.location.assign(result.authorize_url),
  });
  const connect = useMutation({
    mutationFn: async (provider: string) =>
      unwrap(
        await api.POST("/api/v1/integrations/connections", {
          body: {
            provider,
            level,
            username: fields.username ?? "",
            password: fields.password ?? "",
            server_url: fields.server_url ?? "",
            api_key: fields.api_key ?? "",
          },
        }),
      ),
    onSuccess: () => {
      setForm(null);
      setFields({});
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
    },
  });
  const available = providers.filter((p) => p.levels.includes(level));
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {available.map((p) => (
          <Button
            key={p.key}
            size="sm"
            variant="secondary"
            onClick={() => (p.auth === "oauth2" ? start.mutate(p.key) : setForm(p.key))}
          >
            {t("integrations.connect", { provider: p.name })}
          </Button>
        ))}
      </div>
      {form ? (
        <form
          className="space-y-2 rounded-md border border-border p-3"
          aria-label={t("integrations.credentialsFor", {
            provider: available.find((p) => p.key === form)?.name ?? form,
          })}
          onSubmit={(e) => {
            e.preventDefault();
            connect.mutate(form);
          }}
        >
          {(available.find((p) => p.key === form)?.credential_fields ?? []).map((field) => (
            <TextField
              key={field}
              label={t(`integrations.fields.${field}`)}
              type={field === "password" || field === "api_key" ? "password" : "text"}
              autoComplete="off"
              required={field !== "server_url"}
              hint={field === "password" ? t("integrations.appPasswordHint") : undefined}
              value={fields[field] ?? ""}
              onChange={(e) => setFields({ ...fields, [field]: e.target.value })}
            />
          ))}
          <div className="flex gap-2">
            <Button size="sm" type="submit" disabled={connect.isPending}>
              {t("integrations.save")}
            </Button>
            <Button size="sm" variant="ghost" type="button" onClick={() => setForm(null)}>
              {t("common.cancel")}
            </Button>
          </div>
        </form>
      ) : null}
      <ErrorList error={start.error ?? connect.error} />
    </div>
  );
}

/** The person's default video provider for their online lessons (FR-22-4). */
export function MeetingPreferenceForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const pref = useQuery({
    queryKey: ["meeting-preference"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/meeting-preference")),
  });
  const save = useMutation({
    mutationFn: async (body: { provider?: string; use_personal_room?: boolean }) =>
      unwrap(await api.PUT("/api/v1/me/meeting-preference", { body: body as never })),
    onSuccess: (data) => queryClient.setQueryData(["meeting-preference"], data),
  });
  if (!pref.data) return null;
  return (
    <div className="space-y-2">
      <SelectField
        label={t("integrations.myVideoProvider")}
        value={pref.data.provider ?? ""}
        onChange={(e) => save.mutate({ provider: e.target.value })}
        options={[
          { value: "", label: t("integrations.orgDefault") },
          ...VIDEO.map((v) => ({ value: v, label: t(`integrations.video.${v}`) })),
        ]}
      />
      {pref.data.provider === "zoom" ? (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={pref.data.use_personal_room ?? false}
            onChange={(e) => save.mutate({ use_personal_room: e.target.checked })}
          />
          {t("integrations.personalRoom")}
        </label>
      ) : null}
      <ErrorList error={save.error} />
    </div>
  );
}

function VideoDefaults() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["settings", "integrations"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/settings/{area}", { params: { path: { area: "integrations" } } }),
      ),
  });
  const save = useMutation({
    mutationFn: async (values: Record<string, unknown>) =>
      unwrap(
        await api.PATCH("/api/v1/settings/{area}", {
          params: { path: { area: "integrations" } },
          body: { values },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["settings", "integrations"], data),
  });
  const values = settings.data?.values as Record<string, unknown> | undefined;
  if (!values) return null;
  return (
    <div className="max-w-md space-y-3">
      <SelectField
        label={t("integrations.defaultVideo")}
        value={String(values["integrations.video_provider"])}
        onChange={(e) => save.mutate({ "integrations.video_provider": e.target.value })}
        options={VIDEO.map((v) => ({ value: v, label: t(`integrations.video.${v}`) }))}
      />
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={Boolean(values["integrations.auto_create_meetings"])}
          onChange={(e) => save.mutate({ "integrations.auto_create_meetings": e.target.checked })}
        />
        {t("integrations.autoCreate")}
      </label>
      <TextField
        type="number"
        min={0}
        max={120}
        label={t("integrations.joinWindow")}
        defaultValue={String(values["integrations.join_window_minutes"])}
        onBlur={(e) => save.mutate({ "integrations.join_window_minutes": Number(e.target.value) })}
      />
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={Boolean(values["integrations.calendar_two_way"])}
          onChange={(e) => save.mutate({ "integrations.calendar_two_way": e.target.checked })}
        />
        {t("integrations.allowTwoWay")}
      </label>
      {save.isSuccess ? <p role="status">{t("integrations.saved")}</p> : null}
      <ErrorList error={save.error} />
    </div>
  );
}

/** Settings → Integrations (E22): personal calendars and video accounts, the
 * organisation's integrations with their health and errors, and video defaults. */
export function IntegrationsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canView = usePermission("integrations.view");
  const canManage = usePermission("integrations.manage");
  const canSettings = usePermission("org.settings.manage");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["integrations"] });
  const { complete, denied } = useOAuthCompletion(refresh);
  const providers = useQuery({
    queryKey: ["integrations", "providers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/integrations/providers")),
  });
  const mine = useConnections(true);
  const all = useConnections(false);
  const simulated = providers.data?.some((p) => p.simulated);
  const others = (all.data ?? []).filter((c) => !mine.data?.some((m) => m.id === c.id));

  return (
    <div className="max-w-3xl space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">{t("integrations.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("integrations.help")}</p>
      </header>
      {simulated ? <Alert>{t("integrations.simulated")}</Alert> : null}
      {complete.isPending ? (
        <Spinner className="size-5" label={t("integrations.finishing")} />
      ) : null}
      {complete.isSuccess ? <Alert tone="success">{t("integrations.connected")}</Alert> : null}
      {denied ? <Alert tone="warning">{t("integrations.denied")}</Alert> : null}
      <ErrorList error={complete.error} />

      <section className="space-y-3" aria-labelledby="mine-heading">
        <h2 id="mine-heading" className="text-lg font-semibold">
          {t("integrations.mine")}
        </h2>
        <ul className="space-y-3">
          {(mine.data ?? []).map((c) => (
            <ConnectionCard key={c.id} connection={c} showOwner={false} />
          ))}
        </ul>
        {providers.data ? (
          <ConnectProviders level="user" providers={providers.data} returnPath={RETURN_PATH} />
        ) : null}
        <MeetingPreferenceForm />
      </section>

      {canView ? (
        <section className="space-y-3" aria-labelledby="org-heading">
          <h2 id="org-heading" className="text-lg font-semibold">
            {t("integrations.organisation")}
          </h2>
          {others.length ? (
            <ul className="space-y-3">
              {others.map((c) => (
                <ConnectionCard key={c.id} connection={c} showOwner />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">{t("integrations.noneYet")}</p>
          )}
          {canManage && providers.data ? (
            <ConnectProviders
              level="organisation"
              providers={providers.data}
              returnPath={RETURN_PATH}
            />
          ) : null}
        </section>
      ) : null}

      {canSettings ? (
        <section className="space-y-3" aria-labelledby="video-heading">
          <h2 id="video-heading" className="text-lg font-semibold">
            {t("integrations.videoDefaults")}
          </h2>
          <VideoDefaults />
        </section>
      ) : null}
    </div>
  );
}
