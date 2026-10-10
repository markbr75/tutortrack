import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "../api";

type Connection = components["schemas"]["IntegrationConnection"];

const RETURN_PATH = "/portal/tutor/calendar";
const VIDEO = ["builtin", "zoom", "teams", "google_meet"] as const;

function Problem({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  const detail = (error as { detail?: string } | null)?.detail;
  return <Alert tone="danger">{detail || t("errors.generic")}</Alert>;
}

function SyncSettings({ connection }: { connection: Connection }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const path = { params: { path: { id: connection.id } } };
  const page = useQuery({
    queryKey: ["calendar-sync", connection.id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/calendar-sync/connections/{id}/settings", path)),
  });
  const [read, setRead] = useState<string[]>([]);
  const [twoWay, setTwoWay] = useState(false);
  const [write, setWrite] = useState("");
  useEffect(() => {
    if (!page.data) return;
    setRead(page.data.settings.read_calendar_ids as string[]);
    setTwoWay(page.data.settings.two_way ?? false);
    setWrite(page.data.settings.write_calendar_id ?? "");
  }, [page.data]);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/calendar-sync/connections/{id}/settings", {
          ...path,
          body: { read_calendar_ids: read, two_way: twoWay, write_calendar_id: write },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["calendar-sync", connection.id], data),
  });
  if (!page.data) return <Spinner className="size-4" label={t("common.loading")} />;
  return (
    <form
      className="mt-3 space-y-2"
      aria-label={t("integrations.syncSettings")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">{t("integrations.readCalendars")}</legend>
        <p className="text-xs text-muted-foreground">{t("integrations.readHelp")}</p>
        {page.data.calendars.map((c) => (
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
      <SelectField
        label={t("integrations.writeCalendar")}
        value={write}
        onChange={(e) => setWrite(e.target.value)}
        options={[
          { value: "", label: t("integrations.ownCalendar") },
          ...page.data.calendars
            .filter((c) => c.writable)
            .map((c) => ({ value: c.id, label: c.name })),
        ]}
      />
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
      <Button size="sm" type="submit" disabled={save.isPending}>
        {t("common.save")}
      </Button>
      {save.isSuccess ? <p role="status">{t("integrations.saved")}</p> : null}
      <Problem error={save.error} />
    </form>
  );
}

/** Tutor portal: connect personal calendars and a video account, choose what syncs
 * and the default video provider for online lessons (E22). */
export function CalendarSyncPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  const state = params.get("state");
  const started = useRef(false);
  const [icloud, setIcloud] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["integrations"] });

  const complete = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/integrations/oauth/complete", {
          body: { code: code ?? "", state: state ?? "" },
        }),
      ),
    onSettled: () => {
      window.history.replaceState(null, "", window.location.pathname);
      refresh();
    },
  });
  useEffect(() => {
    if (code && state && !started.current) {
      started.current = true;
      complete.mutate();
    }
  }, [code, state, complete]);

  const connections = useQuery({
    queryKey: ["integrations", "mine"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/integrations/connections", { params: { query: { mine: true } } }),
      ).results,
  });
  const preference = useQuery({
    queryKey: ["meeting-preference"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/meeting-preference")),
  });
  const start = useMutation({
    mutationFn: async (provider: string) =>
      unwrap(
        await api.POST("/api/v1/integrations/oauth/start", {
          body: { provider, level: "user", next: RETURN_PATH },
        }),
      ),
    onSuccess: (result) => window.location.assign(result.authorize_url),
  });
  const connectIcloud = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/integrations/connections", {
          body: { provider: "caldav", level: "user", username, password, api_key: "" },
        }),
      ),
    onSuccess: () => {
      setIcloud(false);
      setPassword("");
      refresh();
    },
  });
  const disconnect = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/integrations/connections/{id}/disconnect", {
          params: { path: { id } },
        }),
      ),
    onSuccess: refresh,
  });
  const savePreference = useMutation({
    mutationFn: async (provider: string) =>
      unwrap(await api.PUT("/api/v1/me/meeting-preference", { body: { provider } as never })),
    onSuccess: (data) => queryClient.setQueryData(["meeting-preference"], data),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">{t("integrations.pageTitle")}</h1>
      <p className="text-sm text-muted-foreground">{t("integrations.help")}</p>
      {complete.isSuccess ? <Alert tone="success">{t("integrations.connected")}</Alert> : null}
      {params.get("integration_error") ? (
        <Alert tone="warning">{t("integrations.denied")}</Alert>
      ) : null}
      <Problem error={complete.error ?? start.error ?? disconnect.error} />

      <ul className="space-y-3">
        {(connections.data ?? []).map((c) => (
          <li
            key={c.id}
            className="rounded-lg border border-border p-3"
            aria-label={c.provider_name}
          >
            <p className="font-medium">{c.provider_name}</p>
            <p className="text-sm">
              {t(`integrations.status.${c.status}`)}
              {c.account_name ? ` · ${c.account_name}` : ""}
            </p>
            {c.error ? <Alert tone="warning">{c.error}</Alert> : null}
            {c.capabilities.includes("calendar") ? <SyncSettings connection={c} /> : null}
            <Button
              size="sm"
              variant="ghost"
              className="mt-2"
              onClick={() => disconnect.mutate(c.id)}
            >
              {t("integrations.disconnect")}
            </Button>
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => start.mutate("google")}>
          {t("integrations.connect", { provider: "Google" })}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => start.mutate("microsoft")}>
          {t("integrations.connect", { provider: "Microsoft 365" })}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setIcloud(true)}>
          {t("integrations.connect", { provider: "iCloud" })}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => start.mutate("zoom")}>
          {t("integrations.connect", { provider: "Zoom" })}
        </Button>
      </div>
      {icloud ? (
        <form
          className="space-y-2 rounded-lg border border-border p-3"
          aria-label={t("integrations.credentialsFor", { provider: "iCloud" })}
          onSubmit={(e) => {
            e.preventDefault();
            connectIcloud.mutate();
          }}
        >
          <TextField
            label={t("integrations.fields.username")}
            value={username}
            required
            autoComplete="username"
            onChange={(e) => setUsername(e.target.value)}
          />
          <TextField
            label={t("integrations.fields.password")}
            type="password"
            value={password}
            required
            autoComplete="off"
            hint={t("integrations.appPasswordHint")}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button size="sm" type="submit" disabled={connectIcloud.isPending}>
            {t("integrations.save")}
          </Button>
          <Problem error={connectIcloud.error} />
        </form>
      ) : null}

      {preference.data ? (
        <SelectField
          label={t("integrations.myVideoProvider")}
          value={preference.data.provider ?? ""}
          onChange={(e) => savePreference.mutate(e.target.value)}
          options={[
            { value: "", label: t("integrations.orgDefault") },
            ...VIDEO.map((v) => ({ value: v, label: t(`integrations.video.${v}`) })),
          ]}
        />
      ) : null}
    </div>
  );
}
