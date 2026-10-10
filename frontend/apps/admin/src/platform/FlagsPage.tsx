import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

type Flag = components["schemas"]["Flag"];

function useRefresh() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: ["platform", "flags"] });
}

/** Feature flags with targeting: everyone, plans, a percentage, or named organisations. */
export function FlagsPage() {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const [key, setKey] = useState("");
  const flags = useQuery({
    queryKey: ["platform", "flags"],
    queryFn: async () => unwrap(await api.GET("/api/v1/platform/flags")),
  });
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/platform/flags", { body: { key } })),
    onSuccess: () => {
      setKey("");
      refresh();
    },
  });
  return (
    <div className="max-w-4xl space-y-4">
      <h1 className="text-2xl font-semibold">{t("platform.nav.flags")}</h1>
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <TextField
          label={t("platform.newFlag")}
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
        <Button type="submit" size="sm" loading={create.isPending}>
          {t("platform.add")}
        </Button>
      </form>
      {create.error ? <Alert tone="danger">{create.error.message}</Alert> : null}
      {flags.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      <ul className="space-y-3">
        {flags.data?.map((flag) => (
          <FlagCard key={flag.key} flag={flag} />
        ))}
      </ul>
    </div>
  );
}

function FlagCard({ flag }: { flag: Flag }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const [percent, setPercent] = useState(String(flag.rollout_percent));
  const [plans, setPlans] = useState((flag.plan_keys ?? []).join(", "));
  const [orgId, setOrgId] = useState("");
  const update = useMutation({
    mutationFn: async (body: components["schemas"]["PatchedFlagUpdateRequest"]) =>
      unwrap(
        await api.PATCH("/api/v1/platform/flags/{key}", {
          params: { path: { key: flag.key } },
          body,
        }),
      ),
    onSuccess: refresh,
  });
  const override = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/platform/flags/{key}/overrides", {
          params: { path: { key: flag.key } },
          body: { organisation: orgId, enabled: true, expires_at: null, reason: "" },
        }),
      ),
    onSuccess: () => {
      setOrgId("");
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async (organisation_id: string) =>
      unwrap(
        await api.DELETE("/api/v1/platform/flags/{key}/overrides/{organisation_id}", {
          params: { path: { key: flag.key, organisation_id } },
        }),
      ),
    onSuccess: refresh,
  });
  return (
    <li className="space-y-2 rounded-md border border-border p-4 text-sm">
      <h2 className="font-semibold">{flag.key}</h2>
      {flag.description ? <p className="text-muted-foreground">{flag.description}</p> : null}
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={flag.enabled_globally}
          onChange={(e) => update.mutate({ enabled_globally: e.target.checked })}
        />
        {t("platform.everyone")}
      </label>
      <div className="flex flex-wrap items-end gap-2">
        <TextField
          label={t("platform.rollout")}
          type="number"
          min={0}
          max={100}
          value={percent}
          onChange={(e) => setPercent(e.target.value)}
          className="w-24"
        />
        <TextField
          label={t("platform.plans")}
          hint={t("platform.plansHint")}
          value={plans}
          onChange={(e) => setPlans(e.target.value)}
        />
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            update.mutate({
              rollout_percent: Number(percent),
              plan_keys: plans
                .split(",")
                .map((p) => p.trim())
                .filter(Boolean),
            })
          }
        >
          {t("common.save")}
        </Button>
      </div>
      <ul>
        {flag.overrides.map((o) => (
          <li key={o.organisation} className="flex items-center justify-between">
            <span>
              {o.organisation_name}: {o.enabled ? t("platform.on") : t("platform.off")}
              {o.expires_at ? ` · ${t("platform.until", { date: formatDate(o.expires_at) })}` : ""}
            </span>
            <Button size="sm" variant="ghost" onClick={() => remove.mutate(o.organisation)}>
              {t("platform.remove")}
            </Button>
          </li>
        ))}
      </ul>
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          override.mutate();
        }}
      >
        <TextField
          label={t("platform.organisationId")}
          value={orgId}
          onChange={(e) => setOrgId(e.target.value)}
        />
        <Button type="submit" size="sm" variant="secondary">
          {t("platform.turnOnFor")}
        </Button>
      </form>
      {update.error || override.error ? (
        <Alert tone="danger">{(update.error ?? override.error)?.message}</Alert>
      ) : null}
    </li>
  );
}
