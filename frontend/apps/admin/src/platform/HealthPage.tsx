import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  cn,
  FigureStrip,
  figureCell,
  PageHeader,
  RuledPanel,
  RuledTable,
  SelectField,
} from "@tutortrack/ui";
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

/** Risk in words: at risk waits on customer success (margin red), healthy needs nothing. */
const RISK_CLASS: Record<string, string> = {
  healthy: "text-muted-foreground",
  watch: "font-medium",
  at_risk: "font-semibold text-margin",
};

export function RiskBadge({ risk }: { risk: string }) {
  const { t } = useTranslation();
  return <span className={RISK_CLASS[risk] ?? ""}>{t(`tenantHealth.risk.${risk}`)}</span>;
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
  const list = rows.data?.results ?? [];
  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader
        title={t("tenantHealth.title")}
        description={t("tenantHealth.explain")}
        actions={
          <Button
            size="sm"
            variant="secondary"
            loading={run.isPending}
            onClick={() => run.mutate()}
          >
            {t("tenantHealth.runNow")}
          </Button>
        }
      />
      {run.isSuccess ? <Alert tone="success">{t("tenantHealth.runStarted")}</Alert> : null}
      {counts.data ? (
        <FigureStrip
          label={t("tenantHealth.title")}
          figures={(["healthy", "watch", "at_risk"] as const).map((key) => ({
            key,
            label: t(`tenantHealth.risk.${key}`),
            value: counts.data[key],
            tone: key === "at_risk" && counts.data[key] > 0 ? ("margin" as const) : undefined,
          }))}
        />
      ) : null}
      <RuledPanel
        title={t("designS11.platform.organisationsByScore")}
        aside={
          <SelectField
            label={t("tenantHealth.filter")}
            hideLabel
            size="sm"
            value={risk}
            onChange={(e) => setRisk(e.target.value)}
            options={[
              { value: "", label: t("designS11.platform.anyRisk") },
              { value: "at_risk", label: t("tenantHealth.risk.at_risk") },
              { value: "watch", label: t("tenantHealth.risk.watch") },
              { value: "healthy", label: t("tenantHealth.risk.healthy") },
            ]}
          />
        }
        flush
      >
        <p className="px-5 pt-3 text-xs text-muted-foreground md:hidden">
          {t("designS11.platform.scrollSideways")}
        </p>
        <RuledTable
          caption={t("tenantHealth.title")}
          loading={rows.isPending}
          loadingLabel={t("grid.loading")}
          empty={rows.data && !list.length ? t("designS11.platform.noScores") : undefined}
          columns={[
            { header: t("tenantHealth.organisation") },
            { header: t("tenantHealth.score"), end: true, width: "w-20" },
            { header: t("tenantHealth.riskLabel") },
            ...COMPONENTS.map((c) => ({
              key: c,
              header: t(`tenantHealth.components.${c}`),
              end: true,
            })),
            { header: t("tenantHealth.scoredOn") },
          ]}
        >
          {list.map((row) => (
            <tr key={row.id}>
              <th scope="row" className="min-w-44">
                <Link
                  to="/platform/tenants/$id"
                  params={{ id: row.id }}
                  className="underline-offset-2 hover:underline"
                >
                  {row.name}
                </Link>
                <span className="block text-xs font-normal text-muted-foreground">
                  {row.plan ?? "–"}
                </span>
              </th>
              <td className={cn(figureCell, "font-semibold")}>{row.score}</td>
              <td className="whitespace-nowrap">
                <RiskBadge risk={row.risk} />
              </td>
              {COMPONENTS.map((c) => (
                <td key={c} className={figureCell}>
                  {row.components[c] ?? "–"}
                </td>
              ))}
              <td className="whitespace-nowrap tabular-nums">
                {formatDate(row.scored_on, i18n.language)}
              </td>
            </tr>
          ))}
        </RuledTable>
      </RuledPanel>
    </div>
  );
}

/** The health panel on an organisation's console page: today's score and the last days. */
export function TenantHealthCard({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const history = useQuery({
    queryKey: ["platform", "tenant-health", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/platform/tenants/{id}/health", { params: { path: { id } } })),
  });
  const latest = history.data?.[0];
  return (
    <RuledPanel
      title={t("tenantHealth.cardTitle")}
      aside={latest ? <RiskBadge risk={latest.risk} /> : null}
      rule={latest?.risk === "at_risk" ? "margin" : "border"}
      bodyClassName="px-5 pb-4"
    >
      {!latest ? (
        <p className="pt-4 text-sm text-muted-foreground">{t("tenantHealth.notScored")}</p>
      ) : (
        <div className="space-y-1">
          <FigureStrip
            className="border-y-0"
            columns={4}
            label={t("tenantHealth.cardTitle")}
            figures={[
              {
                key: "score",
                label: t("tenantHealth.score"),
                value: latest.score,
                note: formatDate(latest.date, i18n.language),
              },
              ...COMPONENTS.map((c) => ({
                key: c,
                label: t(`tenantHealth.components.${c}`),
                value: latest.components[c] ?? "–",
              })),
            ]}
          />
          <p className="text-xs text-muted-foreground tabular-nums">
            {t("tenantHealth.trend", {
              scores: (history.data ?? [])
                .slice(0, 14)
                .map((p) => p.score)
                .reverse()
                .join(" → "),
            })}
          </p>
        </div>
      )}
    </RuledPanel>
  );
}
