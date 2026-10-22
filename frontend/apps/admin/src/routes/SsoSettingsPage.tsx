import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  ErrorFallback,
  FactList,
  PageHeader,
  RuledPanel,
  SelectField,
  Spinner,
  TextAreaField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { api, fieldErrors } from "../api";
import { SavedNote } from "../components/SavedNote";

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
  const giveIdp: [string, string][] = saml
    ? [
        [t("orgSso.spEntity"), sso.data.sp_entity_id],
        [t("orgSso.acs"), sso.data.acs_url],
      ]
    : [[t("designS9b.sso.callback"), sso.data.callback_url]];
  return (
    <div>
      <PageHeader title={t("orgSso.title")} description={t("orgSso.intro")} />
      <div className="max-w-3xl space-y-6">
        <form
          aria-labelledby="sso-connection"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <RuledPanel
            flush
            titleId="sso-connection"
            title={t("designS9b.sso.connection")}
            footer={
              <>
                <Button type="submit" loading={save.isPending}>
                  {t("orgSso.save")}
                </Button>
                <SavedNote show={save.isSuccess} text={t("orgSso.saved")} />
              </>
            }
          >
            <div className="grid gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
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
              <div className="sm:col-span-2">
                <TextField
                  label={t("orgSso.domains")}
                  hint={t("orgSso.domainsHint")}
                  value={draft.domains}
                  onChange={(e) => set({ domains: e.target.value })}
                />
              </div>
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
                  <div className="sm:col-span-2">
                    <TextAreaField
                      label={t("orgSso.certificate")}
                      rows={6}
                      className="text-xs break-all"
                      value={draft.idp_certificate ?? ""}
                      onChange={(e) => set({ idp_certificate: e.target.value })}
                    />
                  </div>
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
                </>
              )}
            </div>
            <div className="space-y-2 border-t border-rule px-5 py-4">
              <CheckboxField
                label={t("orgSso.autoProvision")}
                checked={draft.auto_provision ?? false}
                onChange={(e) => set({ auto_provision: e.target.checked })}
              />
              <CheckboxField
                label={t("orgSso.enforce")}
                checked={draft.enforce ?? false}
                onChange={(e) => set({ enforce: e.target.checked })}
              />
              <CheckboxField
                label={t("orgSso.enabled")}
                checked={draft.enabled ?? false}
                onChange={(e) => set({ enabled: e.target.checked })}
              />
            </div>
            {save.error ? (
              <div className="px-5 pb-4">
                <Alert tone="danger">
                  {Object.values(fieldErrors(save.error)).join(" ") || t("errors.generic")}
                </Alert>
              </div>
            ) : null}
          </RuledPanel>
        </form>
        <RuledPanel flush title={t("orgSso.giveIdp")}>
          <FactList items={giveIdp} />
        </RuledPanel>
      </div>
    </div>
  );
}
