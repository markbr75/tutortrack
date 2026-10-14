import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { ConnectProviders } from "../integrations/IntegrationsPage";

type Check = components["schemas"]["BackgroundCheck"];
type CheckDetails = components["schemas"]["CheckDetails"];
const OPEN = new Set(["requested", "invited", "in_progress"]);
const AU_STATES = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"] as const;

/** Online background checks from the tutor record (E18-T11, FR-18-7). */
export function BackgroundChecksCard({ tutorId }: { tutorId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canView = usePermission("compliance.view");
  const canRequest = usePermission("compliance.checks.request");
  const canResults = usePermission("compliance.checks.results");
  const canVerify = usePermission("compliance.verify");
  const formId = useId();
  const checks = useQuery({
    queryKey: ["background-checks", tutorId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/background-checks", { params: { query: { tutor: tutorId } } })),
    enabled: canView,
  });
  const providers = useQuery({
    queryKey: ["background-check-providers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/background-checks/providers")),
    enabled: canRequest,
  });
  const integrationProviders = useQuery({
    queryKey: ["integrations", "providers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/integrations/providers")),
    enabled: canRequest,
  });
  const [provider, setProvider] = useState("");
  const [packageKey, setPackageKey] = useState("");
  const [certificate, setCertificate] = useState("");
  const [stateCode, setStateCode] = useState<string>("NSW");
  const [consent, setConsent] = useState(false);
  const [details, setDetails] = useState<Record<string, CheckDetails>>({});
  const refresh = () =>
    void queryClient.invalidateQueries({ queryKey: ["background-checks", tutorId] });
  const start = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/background-checks", {
          body: {
            tutor: tutorId,
            provider: chosen as components["schemas"]["CheckRequestRequest"]["provider"],
            package: packageKey,
            consent,
            certificate_number: certificate,
            state_code: chosen === "wwcc" ? stateCode : "",
          },
        }),
      ),
    onSuccess: () => {
      setConsent(false);
      setCertificate("");
      refresh();
    },
  });
  const act = useMutation({
    mutationFn: async ({ id, kind }: { id: string; kind: "cancel" | "refresh" }) =>
      kind === "cancel"
        ? unwrap(
            await api.POST("/api/v1/background-checks/{id}/cancel", { params: { path: { id } } }),
          )
        : unwrap(
            await api.POST("/api/v1/background-checks/{id}/refresh", { params: { path: { id } } }),
          ),
    onSuccess: refresh,
  });
  const outcome = useMutation({
    mutationFn: async ({ id, result }: { id: string; result: "clear" | "consider" | "unable" }) =>
      unwrap(
        await api.POST("/api/v1/background-checks/{id}/outcome", {
          params: { path: { id } },
          body: { result },
        }),
      ),
    onSuccess: () => {
      refresh();
      void queryClient.invalidateQueries({ queryKey: ["tutor-compliance", tutorId] });
    },
  });
  const reveal = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.GET("/api/v1/background-checks/{id}/details", { params: { path: { id } } })),
    onSuccess: (data, id) => setDetails((d) => ({ ...d, [id]: data })),
  });
  if (!canView) return null;
  const options = providers.data ?? [];
  const recommended = options.find((p) => p.recommended) ?? options[0];
  const chosen = provider || recommended?.key || "";
  const selected = options.find((p) => p.key === chosen);
  const connectable = (integrationProviders.data ?? []).filter((p) =>
    p.capabilities.includes("background_checks"),
  );
  const rows: Check[] = checks.data?.results ?? [];
  return (
    <section className="rounded-lg border border-border p-4 text-sm" aria-labelledby="bg-checks">
      <h2 id="bg-checks" className="mb-2 font-semibold">
        {t("backgroundChecks.title")}
      </h2>
      {rows.length === 0 ? (
        <p className="text-muted-foreground">{t("backgroundChecks.none")}</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((c) => {
            const shown = details[c.id];
            return (
              <li key={c.id} className="space-y-1 rounded-md border border-border p-2">
                <p>
                  <strong>{c.provider_label}</strong> · {t(`backgroundChecks.status.${c.status}`)}
                  {c.result ? ` · ${t(`backgroundChecks.result.${c.result}`)}` : ""}
                  {c.completed_at ? ` · ${formatDateTime(c.completed_at, i18n.language)}` : ""}
                </p>
                {c.error ? <p className="text-danger">{c.error}</p> : null}
                {c.verification_link ? (
                  <p>
                    <a
                      className="underline"
                      href={c.verification_link}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t("backgroundChecks.verifyOnStatePage")}
                    </a>
                  </p>
                ) : null}
                {shown ? (
                  <dl className="grid grid-cols-[auto_1fr] gap-x-2">
                    <dt>{t("backgroundChecks.certificate")}</dt>
                    <dd>{shown.certificate_number || "–"}</dd>
                    <dt>{t("backgroundChecks.issued")}</dt>
                    <dd>{c.certificate_issue_date ? formatDate(c.certificate_issue_date) : "–"}</dd>
                    {shown.report_url ? (
                      <>
                        <dt>{t("backgroundChecks.report")}</dt>
                        <dd>
                          <a
                            className="underline"
                            href={shown.report_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {t("backgroundChecks.openReport")}
                          </a>
                        </dd>
                      </>
                    ) : null}
                  </dl>
                ) : null}
                <div className="flex flex-wrap gap-1">
                  {canRequest && OPEN.has(c.status) ? (
                    <>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => act.mutate({ id: c.id, kind: "refresh" })}
                      >
                        {t("backgroundChecks.checkNow")}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => act.mutate({ id: c.id, kind: "cancel" })}
                      >
                        {t("backgroundChecks.cancel")}
                      </Button>
                    </>
                  ) : null}
                  {canResults &&
                  c.status === "completed" &&
                  !c.details_purged_at &&
                  !details[c.id] ? (
                    <Button size="sm" variant="secondary" onClick={() => reveal.mutate(c.id)}>
                      {t("backgroundChecks.showResult")}
                    </Button>
                  ) : null}
                  {canVerify &&
                  ((c.provider === "wwcc" && OPEN.has(c.status)) ||
                    (c.status === "completed" && c.result === "consider" && !c.reviewed_at)) ? (
                    <>
                      <Button
                        size="sm"
                        onClick={() => outcome.mutate({ id: c.id, result: "clear" })}
                      >
                        {t("backgroundChecks.markClear")}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => outcome.mutate({ id: c.id, result: "unable" })}
                      >
                        {t("backgroundChecks.markUnable")}
                      </Button>
                    </>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <ErrorList error={act.error ?? outcome.error ?? reveal.error} />
      {canRequest && options.length ? (
        <form
          className="mt-3 space-y-2 border-t border-border pt-3"
          aria-labelledby={`${formId}-title`}
          onSubmit={(e) => {
            e.preventDefault();
            start.mutate();
          }}
        >
          <h3 id={`${formId}-title`} className="font-medium">
            {t("backgroundChecks.start")}
          </h3>
          <SelectField
            label={t("backgroundChecks.provider")}
            value={chosen}
            options={options.map((p) => ({
              value: p.key,
              label: p.recommended ? t("backgroundChecks.recommended", { name: p.title }) : p.title,
            }))}
            onChange={(e) => {
              setProvider(e.target.value);
              setPackageKey("");
            }}
          />
          {selected && selected.packages.length ? (
            <SelectField
              label={t("backgroundChecks.package")}
              value={packageKey || String(selected.packages[0]?.key ?? "")}
              options={selected.packages.map((p) => ({
                value: String(p.key),
                label: String(p.label),
              }))}
              onChange={(e) => setPackageKey(e.target.value)}
            />
          ) : null}
          {chosen === "dbs_update" ? (
            <TextField
              label={t("backgroundChecks.certificateNumber")}
              hint={t("backgroundChecks.certificateHint")}
              value={certificate}
              autoComplete="off"
              onChange={(e) => setCertificate(e.target.value)}
            />
          ) : null}
          {chosen === "wwcc" ? (
            <SelectField
              label={t("backgroundChecks.state")}
              value={stateCode}
              options={AU_STATES.map((s) => ({ value: s, label: s }))}
              onChange={(e) => setStateCode(e.target.value)}
            />
          ) : null}
          {selected && !selected.connected ? (
            <div className="space-y-1">
              <Alert tone="warning">
                {t("backgroundChecks.connectFirst", { name: selected.title })}
              </Alert>
              <ConnectProviders
                level="organisation"
                providers={connectable.filter((p) => p.key === chosen)}
                returnPath={window.location.pathname}
              />
            </div>
          ) : null}
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              className="mt-1 size-4"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            <span>{t("backgroundChecks.consent")}</span>
          </label>
          <Button size="sm" type="submit" disabled={!consent} loading={start.isPending}>
            {t("backgroundChecks.startButton")}
          </Button>
          <ErrorList error={start.error} />
        </form>
      ) : null}
    </section>
  );
}
