import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { SelectField, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { Chart } from "../reporting/Chart";

function percent(value: string | null | undefined, locale: string): string {
  if (value === null || value === undefined) return "—";
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
  const tiles = latest
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
  return (
    <div className="max-w-6xl space-y-6">
      <h1 className="text-2xl font-semibold">{t("saasMetrics.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("saasMetrics.explain")}</p>
      <div className="flex flex-wrap gap-4">
        <div className="w-40">
          <SelectField
            label={t("saasMetrics.currency")}
            value={data?.currency ?? currency}
            onChange={(e) => setCurrency(e.target.value)}
            options={(data?.currencies ?? ["GBP"]).map((c) => ({ value: c, label: c }))}
          />
        </div>
        <div className="w-40">
          <SelectField
            label={t("saasMetrics.period")}
            value={months}
            onChange={(e) => setMonths(e.target.value)}
            options={["3", "6", "12", "24", "36"].map((m) => ({
              value: m,
              label: t("saasMetrics.months", { count: Number(m) }),
            }))}
          />
        </div>
      </div>
      {metrics.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {latest ? (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {tiles.map(([key, value]) => (
            <div key={key} className="rounded-md border border-border p-3">
              <dt className="text-sm text-muted-foreground">{t(`saasMetrics.tiles.${key}`)}</dt>
              <dd className="text-xl font-semibold">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {data && data.months.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">{t("saasMetrics.mrrTrend")}</h2>
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
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">{t("saasMetrics.movements")}</caption>
              <thead>
                <tr className="text-left">
                  {[
                    "month",
                    "mrrCol",
                    "newCol",
                    "reactivationCol",
                    "expansionCol",
                    "contractionCol",
                    "churnCol",
                    "netNewCol",
                    "customersCol",
                    "nrrCol",
                  ].map((key) => (
                    <th key={key} scope="col" className="p-2">
                      {t(`saasMetrics.${key}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.months.map((m) => (
                  <tr key={m.month} className="border-t border-border">
                    <th scope="row" className="p-2 text-left font-normal">
                      {monthLabel(m.month, locale)}
                    </th>
                    <td className="p-2">{formatMoney(m.mrr, locale)}</td>
                    <td className="p-2">{formatMoney(m.new_mrr, locale)}</td>
                    <td className="p-2">{formatMoney(m.reactivation_mrr, locale)}</td>
                    <td className="p-2">{formatMoney(m.expansion_mrr, locale)}</td>
                    <td className="p-2">{formatMoney(m.contraction_mrr, locale)}</td>
                    <td className="p-2">{formatMoney(m.churned_mrr, locale)}</td>
                    <td className="p-2">{formatMoney(m.net_new_mrr, locale)}</td>
                    <td className="p-2">
                      {m.customers}
                      <span className="block text-xs text-muted-foreground">
                        {t("saasMetrics.customersMoved", {
                          added: m.new_customers,
                          lost: m.churned_customers,
                        })}
                      </span>
                    </td>
                    <td className="p-2">{percent(m.net_revenue_retention, locale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      {data ? (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">{t("saasMetrics.trialConversion")}</h2>
          {data.trial_conversion.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("saasMetrics.noData")}</p>
          ) : (
            <table className="w-full max-w-xl text-sm">
              <thead>
                <tr className="text-left">
                  <th scope="col" className="p-2">
                    {t("saasMetrics.signupMonth")}
                  </th>
                  <th scope="col" className="p-2">
                    {t("saasMetrics.trials")}
                  </th>
                  <th scope="col" className="p-2">
                    {t("saasMetrics.converted")}
                  </th>
                  <th scope="col" className="p-2">
                    {t("saasMetrics.rate")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.trial_conversion.map((row) => (
                  <tr key={row.month} className="border-t border-border">
                    <th scope="row" className="p-2 text-left font-normal">
                      {monthLabel(row.month, locale)}
                    </th>
                    <td className="p-2">{row.trials}</td>
                    <td className="p-2">{row.converted}</td>
                    <td className="p-2">{percent(row.conversion_rate, locale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : null}
      {data ? (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">{t("saasMetrics.cohorts")}</h2>
          <p className="text-sm text-muted-foreground">{t("saasMetrics.cohortsExplain")}</p>
          {data.cohorts.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("saasMetrics.noData")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="text-sm">
                <thead>
                  <tr className="text-left">
                    <th scope="col" className="p-2">
                      {t("saasMetrics.cohort")}
                    </th>
                    <th scope="col" className="p-2">
                      {t("saasMetrics.size")}
                    </th>
                    {Array.from(
                      { length: Math.max(...data.cohorts.map((c) => c.logo_retention.length)) },
                      (_, k) => (
                        <th key={k} scope="col" className="p-2">
                          {t("saasMetrics.monthN", { n: k })}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {data.cohorts.map((cohort) => (
                    <tr key={cohort.month} className="border-t border-border">
                      <th scope="row" className="p-2 text-left font-normal">
                        {monthLabel(cohort.month, locale)}
                      </th>
                      <td className="p-2">{cohort.size}</td>
                      {cohort.logo_retention.map((value, k) => (
                        <td key={k} className="p-2">
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
                </tbody>
              </table>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            {latest ? t("saasMetrics.asOf", { date: formatDate(latest.month, locale) }) : null}
          </p>
        </section>
      ) : null}
    </div>
  );
}
