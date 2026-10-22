import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  FigureStrip,
  figureCell,
  PageHeader,
  RuledPanel,
  RuledTable,
  SelectField,
  Spinner,
} from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { Chart } from "../reporting/Chart";

function percent(value: string | null | undefined, locale: string): string {
  if (value === null || value === undefined) return "–";
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(
    Number(value),
  );
}

function monthLabel(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(iso));
}

/** SaaS metrics from E04 subscriptions (E30 FR-30-7), one billing currency at a time. */
export function SaasMetricsPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  const [currency, setCurrency] = useState("");
  const [months, setMonths] = useState("12");
  const metrics = useQuery({
    queryKey: ["platform", "saas-metrics", currency, months],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/platform/saas-metrics", {
          params: { query: { currency: currency || undefined, months: Number(months) } },
        }),
      ),
  });
  const data = metrics.data;
  const latest = data?.months[data.months.length - 1];
  const figures = latest
    ? [
        ["mrr", formatMoney(latest.mrr, locale)],
        ["arr", formatMoney(latest.arr, locale)],
        ["customers", String(latest.customers)],
        ["arpa", formatMoney(latest.arpa, locale)],
        ["nrr", percent(latest.net_revenue_retention, locale)],
        ["logoChurn", percent(latest.logo_churn_rate, locale)],
        ["revenueChurn", percent(latest.revenue_churn_rate, locale)],
        ["trialing", String(latest.trialing)],
        ["pastDue", formatMoney(latest.past_due_mrr, locale)],
      ]
    : [];
  const money = "w-28";
  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader
        title={t("saasMetrics.title")}
        description={t("saasMetrics.explain")}
        actions={
          <>
            <SelectField
              label={t("saasMetrics.currency")}
              hideLabel
              size="sm"
              value={data?.currency ?? currency}
              onChange={(e) => setCurrency(e.target.value)}
              options={(data?.currencies ?? ["GBP"]).map((c) => ({ value: c, label: c }))}
            />
            <SelectField
              label={t("saasMetrics.period")}
              hideLabel
              size="sm"
              value={months}
              onChange={(e) => setMonths(e.target.value)}
              options={["3", "6", "12", "24", "36"].map((m) => ({
                value: m,
                label: t("saasMetrics.months", { count: Number(m) }),
              }))}
            />
          </>
        }
      />
      {metrics.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {latest ? (
        <FigureStrip
          label={t("saasMetrics.title")}
          columns={3}
          figures={figures.map(([key, value]) => ({
            key,
            label: t(`saasMetrics.tiles.${key}`),
            value,
          }))}
        />
      ) : null}
      {data && data.months.length > 0 ? (
        <RuledPanel title={t("saasMetrics.mrrTrend")} flush>
          <div className="border-b border-border px-5 py-4">
            <Chart
              kind="line"
              label={t("saasMetrics.mrrTrend")}
              xLabel={t("saasMetrics.month")}
              srTable={false}
              series={[{ key: "mrr", label: t("saasMetrics.tiles.mrr") }]}
              data={data.months.map((m) => ({
                x: monthLabel(m.month, locale),
                mrr: Number(m.mrr.amount),
              }))}
            />
          </div>
          <RuledTable
            caption={t("saasMetrics.movements")}
            columns={[
              { header: t("saasMetrics.month") },
              ...(
                [
                  "mrrCol",
                  "newCol",
                  "reactivationCol",
                  "expansionCol",
                  "contractionCol",
                  "churnCol",
                  "netNewCol",
                ] as const
              ).map((key) => ({ key, header: t(`saasMetrics.${key}`), end: true, width: money })),
              { header: t("saasMetrics.customersCol"), end: true },
              { header: t("saasMetrics.nrrCol"), end: true },
            ]}
          >
            {data.months.map((m) => (
              <tr key={m.month}>
                <th scope="row" className="whitespace-nowrap">
                  {monthLabel(m.month, locale)}
                </th>
                <td className={figureCell}>{formatMoney(m.mrr, locale)}</td>
                <td className={figureCell}>{formatMoney(m.new_mrr, locale)}</td>
                <td className={figureCell}>{formatMoney(m.reactivation_mrr, locale)}</td>
                <td className={figureCell}>{formatMoney(m.expansion_mrr, locale)}</td>
                <td className={figureCell}>{formatMoney(m.contraction_mrr, locale)}</td>
                <td className={figureCell}>{formatMoney(m.churned_mrr, locale)}</td>
                <td className={figureCell}>{formatMoney(m.net_new_mrr, locale)}</td>
                <td className={figureCell}>
                  {m.customers}
                  <span className="block text-xs text-muted-foreground">
                    {t("saasMetrics.customersMoved", {
                      added: m.new_customers,
                      lost: m.churned_customers,
                    })}
                  </span>
                </td>
                <td className={figureCell}>{percent(m.net_revenue_retention, locale)}</td>
              </tr>
            ))}
          </RuledTable>
        </RuledPanel>
      ) : null}
      {data ? (
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <RuledPanel title={t("saasMetrics.trialConversion")} flush>
            <RuledTable
              caption={t("saasMetrics.trialConversion")}
              empty={data.trial_conversion.length === 0 ? t("saasMetrics.noData") : undefined}
              columns={[
                { header: t("saasMetrics.signupMonth") },
                { header: t("saasMetrics.trials"), end: true },
                { header: t("saasMetrics.converted"), end: true },
                { header: t("saasMetrics.rate"), end: true },
              ]}
            >
              {data.trial_conversion.map((row) => (
                <tr key={row.month}>
                  <th scope="row" className="whitespace-nowrap">
                    {monthLabel(row.month, locale)}
                  </th>
                  <td className={figureCell}>{row.trials}</td>
                  <td className={figureCell}>{row.converted}</td>
                  <td className={figureCell}>{percent(row.conversion_rate, locale)}</td>
                </tr>
              ))}
            </RuledTable>
          </RuledPanel>
          <RuledPanel
            title={t("saasMetrics.cohorts")}
            description={t("saasMetrics.cohortsExplain")}
            flush
            footer={
              latest ? (
                <span className="text-xs text-muted-foreground tabular-nums">
                  {t("saasMetrics.asOf", { date: formatDate(latest.month, locale) })}
                </span>
              ) : null
            }
          >
            <RuledTable
              caption={t("saasMetrics.cohorts")}
              empty={data.cohorts.length === 0 ? t("saasMetrics.noData") : undefined}
              columns={[
                { header: t("saasMetrics.cohort") },
                { header: t("saasMetrics.size"), end: true },
                ...Array.from(
                  {
                    length: Math.max(0, ...data.cohorts.map((c) => c.logo_retention.length)),
                  },
                  (_, k) => ({
                    key: `m${k}`,
                    header: t("saasMetrics.monthN", { n: k }),
                    end: true,
                  }),
                ),
              ]}
            >
              {data.cohorts.map((cohort) => (
                <tr key={cohort.month}>
                  <th scope="row" className="whitespace-nowrap">
                    {monthLabel(cohort.month, locale)}
                  </th>
                  <td className={figureCell}>{cohort.size}</td>
                  {cohort.logo_retention.map((value, k) => (
                    <td key={k} className={figureCell}>
                      {percent(value, locale)}
                      <span className="block text-xs text-muted-foreground">
                        {t("saasMetrics.revenueShort", {
                          value: percent(cohort.revenue_retention[k], locale),
                        })}
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </RuledTable>
          </RuledPanel>
        </div>
      ) : null}
    </div>
  );
}
