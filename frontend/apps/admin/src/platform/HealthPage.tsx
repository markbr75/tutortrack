import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";

type Components = components["schemas"]["HealthComponents"];
const COMPONENTS: Array<keyof Components> = [
  "usage",
  "tutors",
  "payments",
  "reliability",
  "support",
  "nps",
];
const RISK_STYLE: Record<string, string> = {
  healthy: "border-success/40 bg-success/10",
  watch: "border-warning/40 bg-warning/10",
  at_risk: "border-danger/40 bg-danger/10",
};

export function RiskBadge({ risk }: { risk: string }) {
  const { t } = useTranslation();
  return (
    <span className={`rounded border px-1.5 py-0.5 text-xs ${RISK_STYLE[risk] ?? ""}`}>
      {t(`tenantHealth.risk.${risk}`)}
    </span>
  );
}

/** Tenant health for customer success (E30 FR-30-6): lowest scores first. */
export function HealthPage() {
  const { t, i18n } = useTranslation();
  const [risk, setRisk] = useState("");
  const rows = useQuery({
    queryKey: ["platform", "health", risk],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/platform/health", {
          params: { query: risk ? { risk: risk as "at_risk" } : {} },
        }),
      ),
  });
  const counts = useQuery({
    queryKey: ["platform", "risk-counts"],
    queryFn: async () => unwrap(await api.GET("/api/v1/platform/health/risk-counts")),
  });
  const run = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/platform/insights/run")),
  });
  return (
    <div className="max-w-6xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t("tenantHealth.title")}</h1>
        <Button variant="secondary" loading={run.isPending} onClick={() => run.mutate()}>
          {t("tenantHealth.runNow")}
        </Button>
      </div>
      {run.isSuccess ? <Alert tone="success">{t("tenantHealth.runStarted")}</Alert> : null}
      <p className="text-sm text-muted-foreground">{t("tenantHealth.explain")}</p>
      {counts.data ? (
        <dl className="grid grid-cols-3 gap-3">
          {(["healthy", "watch", "at_risk"] as const).map((key) => (
            <div key={key} className={`rounded-md border p-3 ${RISK_STYLE[key]}`}>
              <dt className="text-sm">{t(`tenantHealth.risk.${key}`)}</dt>
              <dd className="text-xl font-semibold">{counts.data[key]}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <div className="max-w-xs">
        <SelectField
          label={t("tenantHealth.filter")}
          value={risk}
          onChange={(e) => setRisk(e.target.value)}
          options={[
            { value: "", label: t("tenantHealth.all") },
            { value: "at_risk", label: t("tenantHealth.risk.at_risk") },
            { value: "watch", label: t("tenantHealth.risk.watch") },
            { value: "healthy", label: t("tenantHealth.risk.healthy") },
          ]}
        />
      </div>
      {rows.isPending ? <Spinner label={t("grid.loading")} /> : null}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{t("tenantHealth.title")}</caption>
          <thead>
            <tr className="text-left">
              <th scope="col" className="p-2">
                {t("tenantHealth.organisation")}
              </th>
              <th scope="col" className="p-2">
                {t("tenantHealth.score")}
              </th>
              <th scope="col" className="p-2">
                {t("tenantHealth.riskLabel")}
              </th>
              {COMPONENTS.map((c) => (
                <th key={c} scope="col" className="p-2">
                  {t(`tenantHealth.components.${c}`)}
                </th>
              ))}
              <th scope="col" className="p-2">
                {t("tenantHealth.scoredOn")}
              </th>
            </tr>
          </thead>
          <tbody>
            {(rows.data?.results ?? []).map((row) => (
              <tr key={row.id} className="border-t border-border">
                <th scope="row" className="p-2 text-left font-normal">
                  <Link
                    to="/platform/tenants/$id"
                    params={{ id: row.id }}
                    className="font-medium underline"
                  >
                    {row.name}
                  </Link>
                  <span className="block text-xs text-muted-foreground">{row.plan ?? "—"}</span>
                </th>
                <td className="p-2 font-semibold">{row.score}</td>
                <td className="p-2">
                  <RiskBadge risk={row.risk} />
                </td>
                {COMPONENTS.map((c) => (
                  <td key={c} className="p-2">
                    {row.components[c] ?? "—"}
                  </td>
                ))}
                <td className="p-2">{formatDate(row.scored_on, i18n.language)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** The health card on an organisation's console page: today's score and the last 90 days. */
export function TenantHealthCard({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const history = useQuery({
    queryKey: ["platform", "tenant-health", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/platform/tenants/{id}/health", { params: { path: { id } } })),
  });
  const latest = history.data?.[0];
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">{t("tenantHealth.cardTitle")}</h2>
      {!latest ? (
        <p className="text-sm text-muted-foreground">{t("tenantHealth.notScored")}</p>
      ) : (
        <>
          <p className="flex items-center gap-2">
            <span className="text-2xl font-semibold">{latest.score}</span>
            <RiskBadge risk={latest.risk} />
            <span className="text-xs text-muted-foreground">
              {formatDate(latest.date, i18n.language)}
            </span>
          </p>
          <dl className="grid grid-cols-3 gap-2 text-sm sm:grid-cols-6">
            {COMPONENTS.map((c) => (
              <div key={c}>
                <dt className="text-xs text-muted-foreground">
                  {t(`tenantHealth.components.${c}`)}
                </dt>
                <dd>{latest.components[c] ?? "—"}</dd>
              </div>
            ))}
          </dl>
          <p className="text-xs text-muted-foreground">
            {t("tenantHealth.trend", {
              scores: (history.data ?? [])
                .slice(0, 14)
                .map((p) => p.score)
                .reverse()
                .join(" → "),
            })}
          </p>
        </>
      )}
    </section>
  );
}
