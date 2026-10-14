import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api";
import {
  currentSubscription,
  disablePush,
  enablePush,
  isIos,
  isStandalone,
  pushSupported,
} from "./push";

type Preference = components["schemas"]["MyPreference"];

/** Push notifications on this phone, my devices, and which channels each kind of message
 * uses (E16-T09, FR-16-9). */
export function NotificationsPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">{t("pwa.notifications")}</h1>
      <ThisDevice />
      <Devices />
      <Preferences />
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
  if (!pushSupported()) {
    body =
      isIos() && !isStandalone() ? (
        <Alert title={t("pwa.iosTitle")}>{t("pwa.iosSteps")}</Alert>
      ) : (
        <p className="text-sm">{t("pwa.unsupported")}</p>
      );
  } else if (config.isPending || subscribed === null) {
    body = <Spinner className="size-5" label={t("grid.loading")} />;
  } else if (!config.data?.enabled) {
    body = <p className="text-sm">{t("pwa.notConfigured")}</p>;
  } else if (denied) {
    body = <Alert tone="warning">{t("pwa.blocked")}</Alert>;
  } else if (subscribed) {
    body = (
      <div className="space-y-2">
        <p className="text-sm">{t("pwa.onHere")}</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => test.mutate()} loading={test.isPending}>
            {t("pwa.sendTest")}
          </Button>
          <Button variant="ghost" onClick={() => turnOff.mutate()} loading={turnOff.isPending}>
            {t("pwa.turnOff")}
          </Button>
        </div>
        {test.isSuccess ? (
          <p role="status" className="text-sm">
            {t("pwa.testSent", { count: test.data.delivered })}
          </p>
        ) : null}
      </div>
    );
  } else {
    body = (
      <div className="space-y-2">
        <p className="text-sm">{t("pwa.offHere")}</p>
        <Button onClick={() => turnOn.mutate()} loading={turnOn.isPending}>
          {t("pwa.turnOn")}
        </Button>
      </div>
    );
  }
  const error = turnOn.error ?? turnOff.error ?? test.error;
  return (
    <section aria-labelledby="this-device" className="space-y-2">
      <h2 id="this-device" className="font-semibold">
        {t("pwa.thisDevice")}
      </h2>
      {body}
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
    </section>
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
    <section aria-labelledby="devices" className="space-y-2">
      <h2 id="devices" className="font-semibold">
        {t("pwa.devices")}
      </h2>
      <ul className="space-y-2">
        {devices.data.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span>
              {d.device || d.push_service} ·{" "}
              {t("pwa.since", { date: formatDateTime(d.created_at, i18n.language) })}
            </span>
            <Button size="sm" variant="ghost" onClick={() => remove.mutate(d.id)}>
              {t("pwa.removeDevice")}
              <span className="sr-only"> {d.device || d.push_service}</span>
            </Button>
          </li>
        ))}
      </ul>
    </section>
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
  if (!rows) return <Spinner className="size-5" label={t("grid.loading")} />;
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
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <h2 id="what-you-hear" className="font-semibold">
        {t("pwa.whatYouHear")}
      </h2>
      <p className="text-sm text-muted-foreground">{t("pwa.whatYouHearHelp")}</p>
      {rows.map((row) => (
        <fieldset key={row.category} className="space-y-1">
          <legend className="text-sm font-medium">{t(`pwa.category.${row.category}`)}</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {row.available.map((channel) => (
              <label key={channel} className="flex min-h-6 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-5"
                  checked={row.channels.includes(channel)}
                  onChange={(e) => toggle(row.category, channel, e.target.checked)}
                />
                {t(`comms.channel.${channel}`)}
              </label>
            ))}
          </div>
        </fieldset>
      ))}
      <Button type="submit" loading={save.isPending}>
        {t("comms.save")}
      </Button>
      {save.isSuccess ? (
        <p role="status" className="text-sm">
          {t("pwa.saved")}
        </p>
      ) : null}
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
    </form>
  );
}
