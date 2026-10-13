import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, ErrorFallback, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { api, fieldErrors } from "../api";

type Sso = components["schemas"]["OrganisationSSO"];
type SsoInput = components["schemas"]["OrganisationSSORequest"];

/** The organisation's own single sign-on (FR-03-2, E03-T12): OpenID Connect or SAML 2.0. */
export function SsoSettingsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<(SsoInput & { domains: string }) | null>(null);
  const sso = useQuery({
    queryKey: ["security", "sso"],
    queryFn: async () => unwrap(await api.GET("/api/v1/security/sso")),
  });
  useEffect(() => {
    if (sso.data && !draft) {
      const data: Sso = sso.data;
      setDraft({ ...data, client_secret: "", domains: (data.email_domains ?? []).join(", ") });
    }
  }, [sso.data, draft]);
  const save = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("not loaded");
      const { domains, ...body } = draft;
      return unwrap(
        await api.PUT("/api/v1/security/sso", {
          body: {
            ...body,
            email_domains: domains
              .split(",")
              .map((d) => d.trim())
              .filter(Boolean),
          },
        }),
      );
    },
    onSuccess: (data) => queryClient.setQueryData(["security", "sso"], data),
  });
  if (sso.isError) {
    return (
      <ErrorFallback
        title={t("errors.generic")}
        retryLabel={t("errors.retry")}
        onRetry={() => void sso.refetch()}
      />
    );
  }
  if (!draft || !sso.data) return <Spinner label={t("grid.loading")} />;
  const saml = draft.protocol === "saml";
  const set = (patch: Partial<SsoInput & { domains: string }>) => setDraft({ ...draft, ...patch });
  return (
    <section className="max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">{t("orgSso.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("orgSso.intro")}</p>
      <form
        className="space-y-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <SelectField
          label={t("orgSso.protocol")}
          value={draft.protocol ?? "oidc"}
          onChange={(e) => set({ protocol: e.target.value as "oidc" | "saml" })}
          options={[
            { value: "oidc", label: "OpenID Connect" },
            { value: "saml", label: "SAML 2.0" },
          ]}
        />
        <TextField
          label={t("orgSso.buttonName")}
          value={draft.name ?? ""}
          onChange={(e) => set({ name: e.target.value })}
        />
        <TextField
          label={t("orgSso.domains")}
          hint={t("orgSso.domainsHint")}
          value={draft.domains}
          onChange={(e) => set({ domains: e.target.value })}
        />
        {saml ? (
          <>
            <TextField
              label={t("orgSso.entityId")}
              value={draft.idp_entity_id ?? ""}
              onChange={(e) => set({ idp_entity_id: e.target.value })}
            />
            <TextField
              label={t("orgSso.ssoUrl")}
              type="url"
              value={draft.idp_sso_url ?? ""}
              onChange={(e) => set({ idp_sso_url: e.target.value })}
            />
            <label className="block text-sm font-medium" htmlFor="sso-cert">
              {t("orgSso.certificate")}
            </label>
            <textarea
              id="sso-cert"
              className="h-32 w-full rounded border border-border bg-background p-2 font-mono text-xs"
              value={draft.idp_certificate ?? ""}
              onChange={(e) => set({ idp_certificate: e.target.value })}
            />
            <Alert tone="info" title={t("orgSso.giveIdp")}>
              <dl className="text-sm">
                <dt className="font-medium">{t("orgSso.spEntity")}</dt>
                <dd className="break-all">{sso.data.sp_entity_id}</dd>
                <dt className="font-medium">{t("orgSso.acs")}</dt>
                <dd className="break-all">{sso.data.acs_url}</dd>
              </dl>
            </Alert>
          </>
        ) : (
          <>
            <TextField
              label={t("orgSso.issuer")}
              type="url"
              value={draft.issuer ?? ""}
              onChange={(e) => set({ issuer: e.target.value })}
            />
            <TextField
              label={t("orgSso.clientId")}
              value={draft.client_id ?? ""}
              onChange={(e) => set({ client_id: e.target.value })}
            />
            <TextField
              label={t("orgSso.clientSecret")}
              type="password"
              autoComplete="off"
              hint={sso.data.has_client_secret ? t("orgSso.secretKept") : undefined}
              value={draft.client_secret ?? ""}
              onChange={(e) => set({ client_secret: e.target.value })}
            />
            <Alert tone="info" title={t("orgSso.giveIdp")}>
              <p className="break-all text-sm">{sso.data.callback_url}</p>
            </Alert>
          </>
        )}
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={draft.auto_provision ?? false}
            onChange={(e) => set({ auto_provision: e.target.checked })}
          />
          {t("orgSso.autoProvision")}
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={draft.enforce ?? false}
            onChange={(e) => set({ enforce: e.target.checked })}
          />
          {t("orgSso.enforce")}
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={draft.enabled ?? false}
            onChange={(e) => set({ enabled: e.target.checked })}
          />
          {t("orgSso.enabled")}
        </label>
        <Button type="submit" disabled={save.isPending}>
          {t("orgSso.save")}
        </Button>
        {save.isSuccess ? <Alert tone="success">{t("orgSso.saved")}</Alert> : null}
        {save.error ? (
          <Alert tone="danger">
            {Object.values(fieldErrors(save.error)).join(" ") || t("errors.generic")}
          </Alert>
        ) : null}
      </form>
    </section>
  );
}
