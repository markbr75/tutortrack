import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  FormPanel,
  NamePlate,
  PageHeader,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  Spinner,
  TextField,
  UnitField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { OrganisationPicker, type OrganisationChoice } from "./OrganisationPicker";

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
    <div className="max-w-4xl space-y-6">
      <PageHeader title={t("platform.nav.flags")} />
      {flags.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {flags.data && !flags.data.length ? (
        <p className="text-sm text-muted-foreground">{t("designS11.platform.noFlags")}</p>
      ) : null}
      {flags.data?.map((flag) => (
        <FlagPanel key={flag.key} flag={flag} />
      ))}
      <FormPanel
        title={t("designS11.platform.newFlag")}
        submit={t("platform.add")}
        pending={create.isPending}
        onSubmit={() => create.mutate()}
        columns={1}
        error={create.error ? <Alert tone="danger">{create.error.message}</Alert> : null}
      >
        <div className="max-w-sm">
          <TextField
            label={t("platform.newFlag")}
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
        </div>
      </FormPanel>
    </div>
  );
}

/** One flag: who it is on for, its rollout and plans, and the organisations named on it. */
function FlagPanel({ flag }: { flag: Flag }) {
  const { t, i18n } = useTranslation();
  const refresh = useRefresh();
  const [percent, setPercent] = useState(String(flag.rollout_percent));
  const [plans, setPlans] = useState((flag.plan_keys ?? []).join(", "));
  const [organisation, setOrganisation] = useState<OrganisationChoice | null>(null);
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
    mutationFn: async (id: string) =>
      unwrap(
        await api.PUT("/api/v1/platform/flags/{key}/overrides", {
          params: { path: { key: flag.key } },
          body: { organisation: id, enabled: true, expires_at: null, reason: "" },
        }),
      ),
    onSuccess: () => {
      setOrganisation(null);
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
    <RuledPanel
      title={flag.key}
      description={flag.description || undefined}
      aside={
        <span className={flag.enabled_globally ? "font-medium" : "text-muted-foreground"}>
          {flag.enabled_globally
            ? t("designS11.platform.onForEveryone")
            : t("designS11.platform.rolloutShort", { percent: flag.rollout_percent })}
        </span>
      }
      flush
    >
      <div className="space-y-4 px-5 py-4">
        <CheckboxField
          label={t("platform.everyone")}
          checked={flag.enabled_globally}
          onChange={(e) => update.mutate({ enabled_globally: e.target.checked })}
        />
        <div className="flex flex-wrap items-start gap-x-4 gap-y-3">
          <UnitField
            label={t("platform.rollout")}
            unit="%"
            min={0}
            max={100}
            value={percent}
            onChange={(e) => setPercent(e.target.value)}
          />
          <div className="min-w-56 flex-1">
            <TextField
              label={t("platform.plans")}
              hint={t("platform.plansHint")}
              value={plans}
              onChange={(e) => setPlans(e.target.value)}
            />
          </div>
        </div>
        {update.error || override.error ? (
          <Alert tone="danger">{(update.error ?? override.error)?.message}</Alert>
        ) : null}
      </div>
      <PanelFooter>
        <Button
          size="sm"
          variant="secondary"
          loading={update.isPending}
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
      </PanelFooter>
      {flag.overrides.length ? (
        <PanelRows className="border-t border-border">
          {flag.overrides.map((o) => (
            <PanelRow key={o.organisation}>
              <NamePlate
                name={o.organisation_name}
                context={[
                  o.enabled ? t("platform.on") : t("platform.off"),
                  o.expires_at
                    ? t("platform.until", { date: formatDate(o.expires_at, i18n.language) })
                    : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
                aside={
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground"
                    onClick={() => remove.mutate(o.organisation)}
                  >
                    {t("platform.remove")}
                  </Button>
                }
              />
            </PanelRow>
          ))}
        </PanelRows>
      ) : null}
      <form
        className="flex flex-wrap items-center gap-2 border-t border-border px-5 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (organisation) override.mutate(organisation.id);
        }}
      >
        <OrganisationPicker
          label={t("followUps.orgPicker.label")}
          value={organisation}
          onChange={setOrganisation}
          exclude={flag.overrides.map((o) => o.organisation)}
          className="min-w-56 flex-1 sm:max-w-sm"
        />
        <Button
          type="submit"
          size="sm"
          variant="secondary"
          className="h-9"
          disabled={!organisation}
          loading={override.isPending}
        >
          {t("platform.turnOnFor")}
        </Button>
      </form>
    </RuledPanel>
  );
}
