import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  CheckboxField,
  figureCell,
  PageHeader,
  RuledPanel,
  RuledTable,
  SelectField,
  UnitField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, usePermission } from "../api";
import { SavedNote } from "../components/SavedNote";
import { useAiStatus } from "./ai";
import { AiError } from "./AiParts";

type FeatureRow = components["schemas"]["AIFeatureSetting"];
type Tone = components["schemas"]["AIToneEnum"];
type Language = components["schemas"]["AILanguageEnum"];

function FeatureRows({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const features = useQuery({
    queryKey: ["ai", "features"],
    queryFn: async () => unwrap(await api.GET("/api/v1/ai/features")),
  });
  const update = useMutation({
    mutationFn: async ({ feature, ...changes }: Partial<FeatureRow> & { feature: string }) =>
      unwrap(
        await api.PATCH("/api/v1/ai/features/{feature}", {
          params: { path: { feature } },
          body: changes as { enabled?: boolean; tone?: Tone | ""; language?: Language | "" },
        }),
      ),
    onSuccess: (rows) => {
      queryClient.setQueryData(["ai", "features"], rows);
      void queryClient.invalidateQueries({ queryKey: ["ai", "status"] });
    },
  });
  return (
    <RuledPanel flush titleId="ai-features" title={t("ai.settings.features")}>
      <RuledTable
        caption={t("ai.settings.features")}
        loading={features.isPending}
        loadingLabel={t("grid.loading")}
        columns={[
          { key: "feature", header: t("ai.settings.feature") },
          { key: "on", header: t("ai.settings.enabled"), center: true, width: "w-20" },
          { key: "tone", header: t("ai.settings.tone"), width: "w-52" },
          { key: "language", header: t("ai.settings.language"), width: "w-52" },
        ]}
      >
        {(features.data ?? []).map((row) => (
          <tr key={row.feature}>
            <th scope="row" className="min-w-44 py-2.5 text-left align-middle font-normal">
              {row.title}
            </th>
            <td className="py-1.5 text-center align-middle">
              <input
                type="checkbox"
                className="size-4 align-middle"
                aria-label={t("ai.settings.turnOn", { feature: row.title })}
                checked={row.enabled}
                disabled={!canManage || update.isPending}
                onChange={(e) => update.mutate({ feature: row.feature, enabled: e.target.checked })}
              />
            </td>
            <td className="py-1.5 align-middle">
              <SelectField
                label={t("ai.settings.toneFor", { feature: row.title })}
                hideLabel
                size="sm"
                value={row.tone}
                disabled={!canManage}
                onChange={(e) =>
                  update.mutate({ feature: row.feature, tone: e.target.value as Tone })
                }
                options={[
                  { value: "", label: t("ai.settings.inherit") },
                  { value: "friendly", label: t("ai.settings.tones.friendly") },
                  { value: "formal", label: t("ai.settings.tones.formal") },
                ]}
              />
            </td>
            <td className="py-1.5 align-middle">
              <SelectField
                label={t("ai.settings.languageFor", { feature: row.title })}
                hideLabel
                size="sm"
                value={row.language}
                disabled={!canManage}
                onChange={(e) =>
                  update.mutate({ feature: row.feature, language: e.target.value as Language })
                }
                options={[
                  { value: "", label: t("ai.settings.inherit") },
                  { value: "en-GB", label: t("ai.settings.languages.en-GB") },
                  { value: "en-US", label: t("ai.settings.languages.en-US") },
                ]}
              />
            </td>
          </tr>
        ))}
      </RuledTable>
      {update.error ? (
        <div className="px-5 py-4">
          <AiError error={update.error} />
        </div>
      ) : null}
    </RuledPanel>
  );
}

function OrganisationDefaults({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["settings", "ai"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/settings/{area}", { params: { path: { area: "ai" } } })),
  });
  const save = useMutation({
    mutationFn: async (values: Record<string, unknown>) =>
      unwrap(
        await api.PATCH("/api/v1/settings/{area}", {
          params: { path: { area: "ai" } },
          body: { values },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["settings", "ai"], data),
  });
  const values = settings.data?.values as Record<string, unknown> | undefined;
  if (!values) return null;
  return (
    <RuledPanel
      flush
      titleId="ai-org"
      title={t("ai.settings.org")}
      description={canManage ? t("designS9b.ai.autosave") : undefined}
      footer={
        save.isSuccess || save.isPending ? (
          save.isPending ? (
            <p className="text-muted-foreground">{t("designS9b.ai.saving")}</p>
          ) : (
            <SavedNote show />
          )
        ) : undefined
      }
    >
      <div className="grid gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
        <SelectField
          label={t("ai.settings.tone")}
          value={String(values["ai.tone"])}
          disabled={!canManage}
          onChange={(e) => save.mutate({ "ai.tone": e.target.value })}
          options={[
            { value: "friendly", label: t("ai.settings.tones.friendly") },
            { value: "formal", label: t("ai.settings.tones.formal") },
          ]}
        />
        <SelectField
          label={t("ai.settings.language")}
          value={String(values["ai.spelling"])}
          disabled={!canManage}
          onChange={(e) => save.mutate({ "ai.spelling": e.target.value })}
          options={[
            { value: "en-GB", label: t("ai.settings.languages.en-GB") },
            { value: "en-US", label: t("ai.settings.languages.en-US") },
          ]}
        />
        <UnitField
          min={0}
          label={t("ai.settings.cap")}
          unit={t("designS9b.ai.credits")}
          defaultValue={String(values["ai.monthly_credit_cap"])}
          disabled={!canManage}
          onBlur={(e) => save.mutate({ "ai.monthly_credit_cap": Number(e.target.value) || 0 })}
        />
        <CheckboxField
          className="self-end pb-2.5"
          label={t("ai.settings.autoClassify")}
          checked={Boolean(values["ai.inbox_auto_classify"])}
          disabled={!canManage}
          onChange={(e) => save.mutate({ "ai.inbox_auto_classify": e.target.checked })}
        />
        {save.error ? (
          <Alert tone="danger" className="sm:col-span-2">
            {save.error.message}
          </Alert>
        ) : null}
      </div>
    </RuledPanel>
  );
}

function Usage() {
  const { t } = useTranslation();
  const usage = useQuery({
    queryKey: ["ai", "usage"],
    queryFn: async () => unwrap(await api.GET("/api/v1/ai/usage")),
  });
  const features = useQuery({
    queryKey: ["ai", "features"],
    queryFn: async () => unwrap(await api.GET("/api/v1/ai/features")),
  });
  if (!usage.data) return null;
  const { totals, by_feature: byFeature, credits, feedback } = usage.data;
  const titleOf = (feature: string) =>
    features.data?.find((f) => f.feature === feature)?.title ?? feature;
  return (
    <RuledPanel
      flush
      titleId="ai-usage"
      title={t("ai.settings.usage")}
      description={
        <span className="tabular-nums">
          {t("ai.settings.totals", {
            requests: totals.requests ?? 0,
            credits: totals.credits ?? 0,
          })}
          {" · "}
          {credits.metered
            ? t("ai.settings.balance", { balance: credits.balance ?? 0 })
            : t("ai.settings.unmetered")}
        </span>
      }
      footer={
        <p className="text-xs text-muted-foreground tabular-nums">
          {t("ai.settings.feedback", { up: feedback.up ?? 0, down: feedback.down ?? 0 })}
        </p>
      }
    >
      <RuledTable
        caption={t("designS9b.ai.byFeature")}
        empty={byFeature.length ? undefined : t("designS9b.ai.noUsage")}
        columns={[
          { key: "feature", header: t("ai.settings.feature") },
          { key: "requests", header: t("designS9b.ai.requests"), end: true, width: "w-28" },
          { key: "credits", header: t("designS9b.ai.creditsHeading"), end: true, width: "w-28" },
        ]}
      >
        {byFeature.map((row) => (
          <tr key={row.feature}>
            <td>{titleOf(row.feature)}</td>
            <td className={figureCell}>{row.requests}</td>
            <td className={figureCell}>{row.credits}</td>
          </tr>
        ))}
      </RuledTable>
    </RuledPanel>
  );
}

/** AI assistant settings (E31-T01): per-feature opt-in, tone and spelling, organisation
 * defaults, the monthly cap and usage. */
export function AiSettingsPage() {
  const { t } = useTranslation();
  const status = useAiStatus();
  const canManage = usePermission("ai.settings.manage");
  const canSeeUsage = usePermission("ai.usage.view");
  return (
    <div className="max-w-4xl">
      <PageHeader title={t("ai.settings.title")} description={t("ai.settings.privacy")} />
      <div className="space-y-6">
        {status.data && !status.data.available ? (
          <Alert tone="warning">{t("ai.settings.notAvailable")}</Alert>
        ) : null}
        <FeatureRows canManage={canManage} />
        <OrganisationDefaults canManage={canManage} />
        {canSeeUsage ? <Usage /> : null}
      </div>
    </div>
  );
}
