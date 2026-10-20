import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, usePermission } from "../api";
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
  if (!features.data) return <Spinner label={t("grid.loading")} />;
  return (
    <section aria-labelledby="ai-features" className="space-y-2">
      <h2 id="ai-features" className="text-lg font-semibold">
        {t("ai.settings.features")}
      </h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left">
            <th scope="col">{t("ai.settings.feature")}</th>
            <th scope="col">{t("ai.settings.enabled")}</th>
            <th scope="col">{t("ai.settings.tone")}</th>
            <th scope="col">{t("ai.settings.language")}</th>
          </tr>
        </thead>
        <tbody>
          {features.data.map((row) => (
            <tr key={row.feature} className="border-t border-border align-middle">
              <th scope="row" className="py-2 pr-2 text-left font-normal">
                {row.title}
              </th>
              <td>
                <input
                  type="checkbox"
                  aria-label={t("ai.settings.turnOn", { feature: row.title })}
                  checked={row.enabled}
                  disabled={!canManage || update.isPending}
                  onChange={(e) =>
                    update.mutate({ feature: row.feature, enabled: e.target.checked })
                  }
                />
              </td>
              <td>
                <SelectField
                  label={t("ai.settings.toneFor", { feature: row.title })}
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
              <td>
                <SelectField
                  label={t("ai.settings.languageFor", { feature: row.title })}
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
        </tbody>
      </table>
      <AiError error={update.error} />
    </section>
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
    <section aria-labelledby="ai-org" className="max-w-md space-y-3">
      <h2 id="ai-org" className="text-lg font-semibold">
        {t("ai.settings.org")}
      </h2>
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
      <TextField
        type="number"
        min={0}
        label={t("ai.settings.cap")}
        defaultValue={String(values["ai.monthly_credit_cap"])}
        disabled={!canManage}
        onBlur={(e) => save.mutate({ "ai.monthly_credit_cap": Number(e.target.value) || 0 })}
      />
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={Boolean(values["ai.inbox_auto_classify"])}
          disabled={!canManage}
          onChange={(e) => save.mutate({ "ai.inbox_auto_classify": e.target.checked })}
        />
        {t("ai.settings.autoClassify")}
      </label>
      {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
    </section>
  );
}

function Usage() {
  const { t } = useTranslation();
  const usage = useQuery({
    queryKey: ["ai", "usage"],
    queryFn: async () => unwrap(await api.GET("/api/v1/ai/usage")),
  });
  if (!usage.data) return null;
  const { totals, by_feature: byFeature, credits, feedback } = usage.data;
  return (
    <section aria-labelledby="ai-usage" className="space-y-2">
      <h2 id="ai-usage" className="text-lg font-semibold">
        {t("ai.settings.usage")}
      </h2>
      <p className="text-sm">
        {t("ai.settings.totals", { requests: totals.requests ?? 0, credits: totals.credits ?? 0 })}
        {" · "}
        {credits.metered
          ? t("ai.settings.balance", { balance: credits.balance ?? 0 })
          : t("ai.settings.unmetered")}
      </p>
      <ul className="text-sm">
        {byFeature.map((row) => (
          <li key={row.feature}>
            {row.feature}:{" "}
            {t("ai.settings.totals", { requests: row.requests, credits: row.credits })}
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        {t("ai.settings.feedback", { up: feedback.up ?? 0, down: feedback.down ?? 0 })}
      </p>
    </section>
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
    <div className="max-w-4xl space-y-6">
      <h1 className="text-2xl font-semibold">{t("ai.settings.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("ai.settings.privacy")}</p>
      {status.data && !status.data.available ? (
        <Alert tone="warning">{t("ai.settings.notAvailable")}</Alert>
      ) : null}
      <FeatureRows canManage={canManage} />
      <OrganisationDefaults canManage={canManage} />
      {canSeeUsage ? <Usage /> : null}
    </div>
  );
}
