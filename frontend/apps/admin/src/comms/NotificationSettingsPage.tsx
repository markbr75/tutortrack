import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PageHeader,
  Panel,
  PanelFooter,
  PanelRows,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

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
    <li className="px-5 py-3">
      <form
        className="grid items-start gap-x-6 gap-y-3 lg:grid-cols-[15rem_minmax(0,1fr)_auto]"
        aria-label={setting.label}
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="min-w-0 lg:pt-1">
          <label className="flex items-start gap-2 text-sm font-medium">
            <input
              type="checkbox"
              className="mt-0.5 size-4 shrink-0"
              checked={enabled}
              disabled={setting.locked}
              aria-describedby={setting.locked ? `locked-${setting.key}` : undefined}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            {setting.label}
          </label>
          {setting.locked ? (
            <p id={`locked-${setting.key}`} className="mt-1 pl-6 text-xs text-muted-foreground">
              {t("templateScope.locked")}
            </p>
          ) : null}
        </div>
        <div className="flex min-w-0 flex-wrap items-start gap-x-6 gap-y-3">
          <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-sm lg:pt-1">
            <legend className="sr-only">{t("comms.channels")}</legend>
            {setting.available_channels.map((c) => (
              <label key={c} className="flex items-center gap-2">
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
              className="w-32 tabular-nums"
              size="sm"
              label={t("comms.hoursBefore")}
              hint={t("comms.hoursHint")}
              value={hours}
              onChange={(e) => setHours(e.target.value)}
            />
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canTemplates ? (
            <Button type="button" size="sm" variant="ghost" onClick={onEdit}>
              {t("comms.editTemplates")}
            </Button>
          ) : null}
          <Button type="submit" size="sm" variant="secondary" loading={save.isPending}>
            {t("comms.save")}
          </Button>
          {save.isSuccess ? (
            <span role="status" className="text-xs text-muted-foreground">
              {t("comms.saved")}
            </span>
          ) : null}
        </div>
      </form>
      <ErrorList error={save.error} />
    </li>
  );
}

/** Which override the editor works on (G4, FR-13-3): a language and/or a branch; blank
 * means every language or every branch. */
function TemplateScope({
  setting,
  channel,
  locale,
  branch,
  onChange,
}: {
  setting: Setting;
  channel: Channel;
  locale: string;
  branch: string;
  onChange: (locale: string, branch: string) => void;
}) {
  const { t } = useTranslation();
  const [language, setLanguage] = useState(locale);
  const branches = useQuery({
    queryKey: ["branches", "template-scope"],
    queryFn: async () => unwrap(await api.GET("/api/v1/branches")),
  });
  const variants = useQuery({
    queryKey: ["message-template-variants", setting.key, channel],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/message-templates/{key}/{channel}/variants", {
          params: { path: { key: setting.key, channel } },
        }),
      ),
  });
  const branchRows = branches.data?.results ?? [];
  return (
    <fieldset className="space-y-3">
      <legend className="mb-2 text-sm font-semibold">{t("templateScope.legend")}</legend>
      <div className="flex flex-wrap items-start gap-3">
        <TextField
          className="w-40"
          label={t("templateScope.language")}
          hint={t("templateScope.languageHint")}
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          onBlur={() => onChange(language.trim(), branch)}
        />
        {branchRows.length > 1 ? (
          <SelectField
            label={t("templateScope.branch")}
            value={branch}
            onChange={(e) => onChange(language.trim(), e.target.value)}
            options={[
              { value: "", label: t("templateScope.allBranches") },
              ...branchRows.map((b) => ({ value: b.id, label: b.name })),
            ]}
          />
        ) : null}
      </div>
      {variants.data?.length ? (
        <div className="space-y-1.5">
          <p className="text-xs font-semibold text-muted-foreground">
            {t("templateScope.overrides")}
          </p>
          <ul className="flex flex-wrap gap-2">
            {variants.data.map((v) => (
              <li key={v.id}>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    setLanguage(v.locale);
                    onChange(v.locale, v.branch ?? "");
                  }}
                >
                  {[v.locale || t("templateScope.anyLanguage"), v.branch_name]
                    .filter(Boolean)
                    .join(" · ")}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </fieldset>
  );
}

function TemplateEditor({ setting, onClose }: { setting: Setting; onClose: () => void }) {
  const { t } = useTranslation();
  // The editor opens above the list: bring it into view and put focus in it.
  useEffect(() => {
    const heading = document.getElementById("template-editor");
    heading?.scrollIntoView?.({ block: "start" });
    heading?.closest("section")?.querySelector<HTMLElement>("select")?.focus();
  }, [setting.key]);
  const [channel, setChannel] = useState<Channel>(setting.available_channels[0]!);
  const [scope, setScope] = useState({ locale: "", branch: "" });
  const key = ["message-template", setting.key, channel, scope.locale, scope.branch];
  const query = {
    ...(scope.locale ? { locale: scope.locale } : {}),
    ...(scope.branch ? { branch: scope.branch } : {}),
  };
  const path = { params: { path: { key: setting.key, channel }, query } };
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
          params: { path: { key: setting.key, channel } },
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
      await api
        .POST("/api/v1/message-templates/{key}/{channel}/test", {
          params: { path: { key: setting.key, channel } },
        })
        .then(unwrap);
      return null;
    },
    onSuccess: (data) => {
      if (data) {
        setDraft(null);
        queryClient.setQueryData(key, data);
        void queryClient.invalidateQueries({ queryKey: ["message-template-variants"] });
      }
    },
  });

  return (
    <Panel
      title={t("comms.templateFor", { label: setting.label })}
      titleId="template-editor"
      aside={
        <Button size="sm" variant="ghost" className="-my-1" onClick={onClose}>
          {t("comms.close")}
        </Button>
      }
      flush
    >
      <div className="space-y-4 px-5 py-4">
        <div className="max-w-xs">
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
        </div>
        <TemplateScope
          setting={setting}
          channel={channel}
          locale={scope.locale}
          branch={scope.branch}
          onChange={(locale, branch) => {
            setScope({ locale, branch });
            setDraft(null);
            preview.reset();
          }}
        />
      </div>
      {template.isPending ? (
        <div className="border-t border-rule px-5 py-4">
          <Spinner label={t("grid.loading")} />
        </div>
      ) : (
        <form
          className="border-t border-rule"
          onSubmit={(e) => {
            e.preventDefault();
            act.mutate("save");
          }}
        >
          <div className="space-y-3 px-5 py-4">
            {channel !== "sms" ? (
              <TextField
                label={t("comms.subject")}
                value={value.subject}
                onChange={(e) => setDraft({ ...value, subject: e.target.value })}
              />
            ) : null}
            <div className="flex flex-col gap-1">
              <label htmlFor="template-body" className="text-sm font-medium">
                {t("comms.body")}
              </label>
              <textarea
                id="template-body"
                className="min-h-48 w-full rounded-md border border-field bg-surface px-3 py-2 text-sm"
                aria-describedby="template-variables"
                value={value.body}
                onChange={(e) => setDraft({ ...value, body: e.target.value })}
              />
              <p id="template-variables" className="text-xs leading-6 text-muted-foreground">
                {t("comms.variables")}{" "}
                {(template.data?.variables ?? []).map((v) => (
                  <code
                    key={v}
                    className="mr-1 rounded border border-border px-1 py-0.5 font-[inherit] text-foreground"
                  >{`{{ ${v} }}`}</code>
                ))}
              </p>
            </div>
            {preview.data ? (
              <div
                className="space-y-1 rounded-md border border-border px-4 py-3 text-sm"
                aria-live="polite"
              >
                <p className="text-xs font-semibold text-muted-foreground">{t("comms.preview")}</p>
                {preview.data.subject ? (
                  <p className="font-semibold">{preview.data.subject}</p>
                ) : null}
                <p className="whitespace-pre-wrap">{preview.data.body}</p>
                {channel === "sms" ? (
                  <p className="text-xs text-muted-foreground">
                    {t("comms.segments", { count: preview.data.segments })}
                  </p>
                ) : null}
              </div>
            ) : null}
            {act.isSuccess && !act.data ? (
              <Alert tone="success">{t("comms.testSent")}</Alert>
            ) : null}
            <ErrorList error={act.error ?? preview.error} />
          </div>
          <PanelFooter>
            <Button type="button" size="sm" variant="secondary" onClick={() => preview.mutate()}>
              {t("comms.preview")}
            </Button>
            {channel !== "sms" ? (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={() => act.mutate("test")}
              >
                {t("comms.sendTest")}
              </Button>
            ) : null}
            <Button type="submit" size="sm" loading={act.isPending && act.variables === "save"}>
              {t("comms.saveTemplate")}
            </Button>
            {template.data?.customised ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="text-muted-foreground"
                onClick={() => act.mutate("revert")}
              >
                {t("comms.revert")}
              </Button>
            ) : null}
            {template.data?.customised ? (
              <span className="text-xs text-muted-foreground sm:ml-auto">
                {t("comms.version", { n: template.data.version })}
              </span>
            ) : null}
          </PanelFooter>
        </form>
      )}
    </Panel>
  );
}

const CATEGORIES = ["scheduling", "reports", "billing", "account", "messages", "staff"] as const;

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
    <div className="max-w-5xl">
      <PageHeader title={t("comms.title")} description={t("comms.help")} />
      <div className="space-y-6">
        {current ? <TemplateEditor setting={current} onClose={() => setEditing(null)} /> : null}
        {settings.isPending ? (
          <Spinner label={t("grid.loading")} />
        ) : (
          CATEGORIES.map((category) => {
            const rows = (settings.data ?? []).filter((s) => s.category === category);
            if (!rows.length) return null;
            return (
              <Panel key={category} title={t(`comms.category.${category}`)} flush>
                <PanelRows>
                  {rows.map((s) => (
                    <SettingRow
                      key={`${s.key}-${s.enabled}-${s.channels.join()}`}
                      setting={s}
                      onEdit={() => setEditing(s.key)}
                    />
                  ))}
                </PanelRows>
              </Panel>
            );
          })
        )}
      </div>
    </div>
  );
}
