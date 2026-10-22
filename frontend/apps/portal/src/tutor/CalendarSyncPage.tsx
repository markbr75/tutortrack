import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  PanelFooter,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import { PanelEmpty, PortalHeader, Word } from "../layout/PortalPage";

type Connection = components["schemas"]["IntegrationConnection"];

const RETURN_PATH = "/portal/tutor/calendar";
const VIDEO = ["builtin", "zoom", "teams", "google_meet"] as const;
/** What a tutor can connect: the provider key and its name (brand names stay as written). */
const PROVIDERS = [
  { key: "google", name: "Google" },
  { key: "microsoft", name: "Microsoft 365" },
  { key: "caldav", name: "iCloud" },
  { key: "zoom", name: "Zoom" },
] as const;

const quiet = "text-muted-foreground hover:text-foreground";

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
  if (!page.data) return <Spinner className="px-5 py-3" label={t("common.loading")} />;
  return (
    <form
      className="border-t border-rule"
      aria-label={t("integrations.syncSettings")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="grid items-start gap-x-6 gap-y-4 px-5 py-4 sm:grid-cols-2">
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t("integrations.readCalendars")}</legend>
          <p className="text-xs text-muted-foreground">{t("integrations.readHelp")}</p>
          {page.data.calendars.map((c) => (
            <CheckboxField
              key={c.id}
              label={c.name}
              checked={read.includes(c.id)}
              onChange={(e) =>
                setRead(e.target.checked ? [...read, c.id] : read.filter((id) => id !== c.id))
              }
            />
          ))}
        </fieldset>
        <div className="space-y-3">
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
          <div>
            <CheckboxField
              label={t("integrations.twoWay")}
              checked={twoWay}
              disabled={!page.data.two_way_allowed}
              onChange={(e) => setTwoWay(e.target.checked)}
            />
            <p className="mt-1 pl-6 text-xs text-muted-foreground">
              {t("integrations.twoWayHelp")}
            </p>
          </div>
        </div>
      </div>
      {save.error ? (
        <div className="px-5 pb-4">
          <Problem error={save.error} />
        </div>
      ) : null}
      <PanelFooter>
        <Button size="sm" type="submit" disabled={save.isPending}>
          {t("common.save")}
        </Button>
        <span role="status" className="text-sm text-success">
          {save.isSuccess ? t("integrations.saved") : ""}
        </span>
      </PanelFooter>
    </form>
  );
}

/** Tutor portal: connect personal calendars and a video account, choose what syncs
 * and the default video provider for online lessons (E22). Connections are ruled rows; a
 * new one is chosen from one select and its Connect button, never a cloud of buttons. */
export function CalendarSyncPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  const state = params.get("state");
  const started = useRef(false);
  const [adding, setAdding] = useState<string>(PROVIDERS[0].key);
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
  const chosen = PROVIDERS.find((p) => p.key === adding) ?? PROVIDERS[0];
  const rows = connections.data ?? [];

  return (
    <div>
      <PortalHeader title={t("integrations.pageTitle")} description={t("integrations.help")} />
      <div className="space-y-6">
        {complete.isSuccess ? <Alert tone="success">{t("integrations.connected")}</Alert> : null}
        {params.get("integration_error") ? (
          <Alert tone="warning">{t("integrations.denied")}</Alert>
        ) : null}
        <Problem error={complete.error ?? start.error ?? disconnect.error} />

        <RuledPanel label={t("designS10.connections")} flush>
          {rows.length ? (
            <ul className="divide-y divide-border">
              {rows.map((c) => (
                <li key={c.id} aria-label={c.provider_name}>
                  <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-5 py-3">
                    <div className="min-w-0">
                      <p className="font-medium">{c.provider_name}</p>
                      <p className="text-xs text-muted-foreground">
                        <Word
                          tone={c.status === "needs_reconnect" ? "margin" : "ink"}
                          className={
                            c.status === "error" ? "font-medium text-danger" : "text-foreground"
                          }
                        >
                          {t(`integrations.status.${c.status}`)}
                        </Word>
                        {c.account_name ? ` · ${c.account_name}` : ""}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      className={quiet}
                      onClick={() => disconnect.mutate(c.id)}
                    >
                      {t("integrations.disconnect")}
                      <span className="sr-only"> {c.provider_name}</span>
                    </Button>
                  </div>
                  {c.error ? (
                    <div className="px-5 pb-3">
                      <Alert tone="warning">{c.error}</Alert>
                    </div>
                  ) : null}
                  {c.capabilities.includes("calendar") ? <SyncSettings connection={c} /> : null}
                </li>
              ))}
            </ul>
          ) : connections.isPending ? null : (
            <PanelEmpty>{t("designS10.noConnections")}</PanelEmpty>
          )}
          <div className="flex flex-wrap items-end gap-2 border-t border-border px-5 py-3">
            <div className="min-w-40 flex-1 sm:max-w-72">
              <SelectField
                size="sm"
                label={t("designS10.addConnection")}
                hideLabel
                value={adding}
                onChange={(e) => {
                  setAdding(e.target.value);
                  setIcloud(false);
                }}
                options={PROVIDERS.map((p) => ({ value: p.key, label: p.name }))}
              />
            </div>
            <Button
              size="sm"
              variant="secondary"
              className="h-9"
              onClick={() => (adding === "caldav" ? setIcloud(true) : start.mutate(adding))}
            >
              {t("integrations.connect", { provider: chosen.name })}
            </Button>
          </div>
        </RuledPanel>
        {icloud ? (
          <form
            aria-label={t("integrations.credentialsFor", { provider: "iCloud" })}
            onSubmit={(e) => {
              e.preventDefault();
              connectIcloud.mutate();
            }}
          >
            <RuledPanel title={t("integrations.credentialsFor", { provider: "iCloud" })} flush>
              <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
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
              </div>
              {connectIcloud.error ? (
                <div className="px-5 pb-4">
                  <Problem error={connectIcloud.error} />
                </div>
              ) : null}
              <PanelFooter>
                <Button type="submit" disabled={connectIcloud.isPending}>
                  {t("integrations.save")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  className={quiet}
                  onClick={() => setIcloud(false)}
                >
                  {t("common.cancel")}
                </Button>
              </PanelFooter>
            </RuledPanel>
          </form>
        ) : null}

        {preference.data ? (
          <RuledPanel title={t("designS10.onlineLessons")}>
            <div className="max-w-sm">
              <SelectField
                label={t("integrations.myVideoProvider")}
                value={preference.data.provider ?? ""}
                onChange={(e) => savePreference.mutate(e.target.value)}
                options={[
                  { value: "", label: t("integrations.orgDefault") },
                  ...VIDEO.map((v) => ({ value: v, label: t(`integrations.video.${v}`) })),
                ]}
              />
            </div>
          </RuledPanel>
        ) : null}
      </div>
    </div>
  );
}
