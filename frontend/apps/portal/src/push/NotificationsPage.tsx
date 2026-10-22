import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  NamePlate,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api";
import { DigestPreferences } from "../digests/DigestPreferences";
import { CheckField, PanelLoading, PortalHeader } from "../layout/PortalPage";
import {
  currentSubscription,
  disablePush,
  enablePush,
  isIos,
  isStandalone,
  pushSupported,
} from "./push";

type Preference = components["schemas"]["MyPreference"];

const quiet = "text-muted-foreground hover:text-foreground";

/** Push notifications on this phone, my devices, and which channels each kind of message
 * uses (E16-T09, FR-16-9). */
export function NotificationsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <PortalHeader title={t("pwa.notifications")} />
      <div className="space-y-6">
        <ThisDevice />
        <Devices />
        <Preferences />
        <DigestPreferences />
      </div>
    </div>
  );
}

function ThisDevice() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const config = useQuery({
    queryKey: ["push", "config"],
    queryFn: async () => unwrap(await api.GET("/api/v1/push-subscriptions/config")),
  });
  const [subscribed, setSubscribed] = useState<boolean | null>(null);
  const [denied, setDenied] = useState(
    () => pushSupported() && Notification.permission === "denied",
  );
  useEffect(() => {
    void currentSubscription().then((s) => setSubscribed(Boolean(s)));
  }, []);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["push", "devices"] });
  const turnOn = useMutation({
    mutationFn: async () => enablePush(config.data?.vapid_public_key ?? ""),
    onSuccess: (state) => {
      setDenied(state === "denied");
      setSubscribed(state === "on");
      refresh();
    },
  });
  const turnOff = useMutation({
    mutationFn: disablePush,
    onSuccess: () => {
      setSubscribed(false);
      refresh();
    },
  });
  const test = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/push-subscriptions/test")),
  });

  let body: JSX.Element;
  let footer: JSX.Element | null = null;
  if (!pushSupported()) {
    body =
      isIos() && !isStandalone() ? (
        <Alert title={t("pwa.iosTitle")}>{t("pwa.iosSteps")}</Alert>
      ) : (
        <p className="text-sm text-muted-foreground">{t("pwa.unsupported")}</p>
      );
  } else if (config.isPending || subscribed === null) {
    body = <PanelLoading label={t("grid.loading")} />;
  } else if (!config.data?.enabled) {
    body = <p className="text-sm text-muted-foreground">{t("pwa.notConfigured")}</p>;
  } else if (denied) {
    body = <Alert tone="warning">{t("pwa.blocked")}</Alert>;
  } else if (subscribed) {
    body = (
      <div className="space-y-1">
        <p className="text-sm">{t("pwa.onHere")}</p>
        {test.isSuccess ? (
          <p role="status" className="text-sm text-success">
            {t("pwa.testSent", { count: test.data.delivered })}
          </p>
        ) : null}
      </div>
    );
    footer = (
      <>
        <Button variant="secondary" onClick={() => test.mutate()} loading={test.isPending}>
          {t("pwa.sendTest")}
        </Button>
        <Button
          variant="ghost"
          className={quiet}
          onClick={() => turnOff.mutate()}
          loading={turnOff.isPending}
        >
          {t("pwa.turnOff")}
        </Button>
      </>
    );
  } else {
    body = <p className="text-sm text-muted-foreground">{t("pwa.offHere")}</p>;
    footer = (
      <Button onClick={() => turnOn.mutate()} loading={turnOn.isPending}>
        {t("pwa.turnOn")}
      </Button>
    );
  }
  const error = turnOn.error ?? turnOff.error ?? test.error;
  return (
    <RuledPanel
      title={t("pwa.thisDevice")}
      titleId="this-device"
      flush
      footer={footer ?? undefined}
    >
      <div className="space-y-3 px-5 py-4">
        {body}
        {error ? <Alert tone="danger">{error.message}</Alert> : null}
      </div>
    </RuledPanel>
  );
}

function Devices() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const devices = useQuery({
    queryKey: ["push", "devices"],
    queryFn: async () => unwrap(await api.GET("/api/v1/push-subscriptions")).results,
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      api.DELETE("/api/v1/push-subscriptions/{id}", { params: { path: { id } } }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["push", "devices"] }),
  });
  if (!devices.data?.length) return null;
  return (
    <RuledPanel title={t("pwa.devices")} titleId="devices" flush>
      <PanelRows>
        {devices.data.map((d) => (
          <PanelRow key={d.id}>
            <NamePlate
              name={d.device || d.push_service}
              context={
                <span className="tabular-nums">
                  {t("pwa.since", { date: formatDateTime(d.created_at, i18n.language) })}
                </span>
              }
              aside={
                <Button
                  size="sm"
                  variant="ghost"
                  className={quiet}
                  onClick={() => remove.mutate(d.id)}
                >
                  {t("pwa.removeDevice")}
                  <span className="sr-only"> {d.device || d.push_service}</span>
                </Button>
              }
            />
          </PanelRow>
        ))}
      </PanelRows>
    </RuledPanel>
  );
}

function Preferences() {
  const { t } = useTranslation();
  const prefs = useQuery({
    queryKey: ["push", "preferences"],
    queryFn: async () => unwrap(await api.GET("/api/v1/communication-preferences/mine")),
  });
  const [rows, setRows] = useState<Preference[] | null>(null);
  useEffect(() => {
    if (prefs.data && rows === null) setRows(prefs.data.preferences);
  }, [prefs.data, rows]);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/communication-preferences/mine", {
          body: {
            preferences: (rows ?? []).map((r) => ({ category: r.category, channels: r.channels })),
          },
        }),
      ),
    onSuccess: (data) => setRows(data.preferences),
  });
  const toggle = (category: string, channel: Preference["channels"][number], on: boolean) =>
    setRows((current) =>
      (current ?? []).map((r) =>
        r.category !== category
          ? r
          : {
              ...r,
              channels: on
                ? r.available.filter((c) => c === channel || r.channels.includes(c))
                : r.channels.filter((c) => c !== channel),
            },
      ),
    );
  return (
    <form
      aria-labelledby="what-you-hear"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <RuledPanel
        title={t("pwa.whatYouHear")}
        titleId="what-you-hear"
        description={t("pwa.whatYouHearHelp")}
        flush
      >
        {!rows ? (
          <PanelLoading label={t("grid.loading")} />
        ) : (
          <div className="divide-y divide-rule">
            {rows.map((row) => (
              <fieldset
                key={row.category}
                className="grid gap-x-4 gap-y-2 px-5 py-3 sm:grid-cols-[12rem_minmax(0,1fr)]"
              >
                <legend className="float-left text-sm font-medium sm:pt-0.5">
                  {t(`pwa.category.${row.category}`)}
                </legend>
                <div className="flex flex-wrap gap-x-5 gap-y-1">
                  {row.available.map((channel) => (
                    <CheckField
                      key={channel}
                      className="min-h-6 items-center"
                      label={t(`comms.channel.${channel}`)}
                      checked={row.channels.includes(channel)}
                      onChange={(e) => toggle(row.category, channel, e.target.checked)}
                    />
                  ))}
                </div>
              </fieldset>
            ))}
          </div>
        )}
        {save.error ? (
          <div className="px-5 pb-4">
            <Alert tone="danger">{save.error.message}</Alert>
          </div>
        ) : null}
        <PanelFooter>
          <Button type="submit" loading={save.isPending}>
            {t("comms.save")}
          </Button>
          <span role="status" className="text-sm text-success">
            {save.isSuccess ? t("pwa.saved") : ""}
          </span>
        </PanelFooter>
      </RuledPanel>
    </form>
  );
}
