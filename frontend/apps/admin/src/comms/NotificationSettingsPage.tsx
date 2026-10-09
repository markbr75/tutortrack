import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";

type Setting = components["schemas"]["NotificationSetting"];
type Channel = components["schemas"]["MessageChannelEnum"];

function SettingRow({ setting, onEdit }: { setting: Setting; onEdit: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canTemplates = usePermission("comms.template.manage");
  const [enabled, setEnabled] = useState(setting.enabled);
  const [channels, setChannels] = useState<Channel[]>(setting.channels);
  const [hours, setHours] = useState(setting.timing.map((m) => String(m / 60)).join(", "));
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/notification-settings/{key}", {
          params: { path: { key: setting.key } },
          body: {
            enabled,
            channels,
            timing: setting.has_timing
              ? hours
                  .split(",")
                  .map((h) => Math.round(Number(h.trim()) * 60))
                  .filter((m) => m > 0)
              : null,
          },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notification-settings"] }),
  });
  return (
    <li className="space-y-2 rounded-md border border-border p-3">
      <form
        className="flex flex-wrap items-end gap-4"
        aria-label={setting.label}
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <label className="flex w-64 items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            className="size-4"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          {setting.label}
        </label>
        <fieldset className="flex gap-3 text-sm">
          <legend className="sr-only">{t("comms.channels")}</legend>
          {setting.available_channels.map((c) => (
            <label key={c} className="flex items-center gap-1">
              <input
                type="checkbox"
                className="size-4"
                checked={channels.includes(c)}
                onChange={(e) =>
                  setChannels((current) =>
                    e.target.checked ? [...current, c] : current.filter((x) => x !== c),
                  )
                }
              />
              {t(`comms.channel.${c}`)}
            </label>
          ))}
        </fieldset>
        {setting.has_timing ? (
          <TextField
            className="w-40"
            label={t("comms.hoursBefore")}
            hint={t("comms.hoursHint")}
            value={hours}
            onChange={(e) => setHours(e.target.value)}
          />
        ) : null}
        <Button type="submit" size="sm" variant="secondary" disabled={save.isPending}>
          {t("comms.save")}
        </Button>
        {canTemplates ? (
          <Button type="button" size="sm" variant="ghost" onClick={onEdit}>
            {t("comms.editTemplates")}
          </Button>
        ) : null}
      </form>
      {save.isSuccess ? <p className="text-xs text-muted-foreground">{t("comms.saved")}</p> : null}
      <ErrorList error={save.error} />
    </li>
  );
}

function TemplateEditor({ setting, onClose }: { setting: Setting; onClose: () => void }) {
  const { t } = useTranslation();
  const [channel, setChannel] = useState<Channel>(setting.available_channels[0]!);
  const key = ["message-template", setting.key, channel];
  const path = { params: { path: { key: setting.key, channel } } };
  const template = useQuery({
    queryKey: key,
    queryFn: async () => unwrap(await api.GET("/api/v1/message-templates/{key}/{channel}", path)),
  });
  const [draft, setDraft] = useState<{ subject: string; body: string } | null>(null);
  const value = draft ?? {
    subject: template.data?.subject ?? "",
    body: template.data?.body ?? "",
  };
  const queryClient = useQueryClient();
  const preview = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/message-templates/{key}/{channel}/preview", {
          ...path,
          body: value,
        }),
      ),
  });
  const act = useMutation({
    mutationFn: async (kind: "save" | "revert" | "test") => {
      if (kind === "save")
        return unwrap(
          await api.PUT("/api/v1/message-templates/{key}/{channel}", { ...path, body: value }),
        );
      if (kind === "revert")
        return unwrap(await api.DELETE("/api/v1/message-templates/{key}/{channel}", path));
      await api.POST("/api/v1/message-templates/{key}/{channel}/test", path).then(unwrap);
      return null;
    },
    onSuccess: (data) => {
      if (data) {
        setDraft(null);
        queryClient.setQueryData(key, data);
      }
    },
  });

  return (
    <section
      aria-labelledby="template-editor"
      className="space-y-3 rounded-md border border-border p-4"
    >
      <div className="flex items-center justify-between">
        <h2 id="template-editor" className="text-lg font-semibold">
          {t("comms.templateFor", { label: setting.label })}
        </h2>
        <Button size="sm" variant="ghost" onClick={onClose}>
          {t("comms.close")}
        </Button>
      </div>
      <SelectField
        label={t("comms.channelLabel")}
        value={channel}
        onChange={(e) => {
          setChannel(e.target.value as Channel);
          setDraft(null);
          preview.reset();
        }}
        options={setting.available_channels.map((c) => ({
          value: c,
          label: t(`comms.channel.${c}`),
        }))}
      />
      {template.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            act.mutate("save");
          }}
        >
          {channel !== "sms" ? (
            <TextField
              label={t("comms.subject")}
              value={value.subject}
              onChange={(e) => setDraft({ ...value, subject: e.target.value })}
            />
          ) : null}
          <div className="space-y-1">
            <label htmlFor="template-body" className="text-sm font-medium">
              {t("comms.body")}
            </label>
            <textarea
              id="template-body"
              className="min-h-48 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm"
              value={value.body}
              onChange={(e) => setDraft({ ...value, body: e.target.value })}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            {t("comms.variables")}{" "}
            {(template.data?.variables ?? []).map((v) => (
              <code key={v} className="mr-1 rounded bg-muted px-1">{`{{ ${v} }}`}</code>
            ))}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={act.isPending}>
              {t("comms.saveTemplate")}
            </Button>
            <Button type="button" variant="secondary" onClick={() => preview.mutate()}>
              {t("comms.preview")}
            </Button>
            {channel !== "sms" ? (
              <Button type="button" variant="secondary" onClick={() => act.mutate("test")}>
                {t("comms.sendTest")}
              </Button>
            ) : null}
            {template.data?.customised ? (
              <Button type="button" variant="ghost" onClick={() => act.mutate("revert")}>
                {t("comms.revert")}
              </Button>
            ) : null}
          </div>
          {template.data?.customised ? (
            <p className="text-xs text-muted-foreground">
              {t("comms.version", { n: template.data.version })}
            </p>
          ) : null}
          {act.isSuccess && !act.data ? <Alert tone="success">{t("comms.testSent")}</Alert> : null}
          <ErrorList error={act.error ?? preview.error} />
        </form>
      )}
      {preview.data ? (
        <div className="rounded-md bg-muted p-3 text-sm" aria-live="polite">
          {preview.data.subject ? <p className="font-semibold">{preview.data.subject}</p> : null}
          <p className="whitespace-pre-wrap">{preview.data.body}</p>
          {channel === "sms" ? (
            <p className="mt-2 text-xs">{t("comms.segments", { count: preview.data.segments })}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

const CATEGORIES = ["scheduling", "reports", "billing", "account", "staff"] as const;

/** Which notifications go out, how and when, and their templates (FR-13-2/3). */
export function NotificationSettingsPage() {
  const { t } = useTranslation();
  const [editing, setEditing] = useState<string | null>(null);
  const settings = useQuery({
    queryKey: ["notification-settings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/notification-settings")),
  });
  const current = settings.data?.find((s) => s.key === editing);
  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-2xl font-semibold">{t("comms.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("comms.help")}</p>
      {current ? <TemplateEditor setting={current} onClose={() => setEditing(null)} /> : null}
      {settings.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : (
        CATEGORIES.map((category) => {
          const rows = (settings.data ?? []).filter((s) => s.category === category);
          if (!rows.length) return null;
          return (
            <section key={category} aria-labelledby={`cat-${category}`} className="space-y-2">
              <h2 id={`cat-${category}`} className="font-semibold">
                {t(`comms.category.${category}`)}
              </h2>
              <ul className="space-y-2">
                {rows.map((s) => (
                  <SettingRow
                    key={`${s.key}-${s.enabled}-${s.channels.join()}`}
                    setting={s}
                    onEdit={() => setEditing(s.key)}
                  />
                ))}
              </ul>
            </section>
          );
        })
      )}
    </div>
  );
}
