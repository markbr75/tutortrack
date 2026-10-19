import { unwrap } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { SelectField, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

/** NPS/CSAT and product usage across organisations (E30 FR-30-6). */
export function InsightsPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  const [days, setDays] = useState("30");
  const nps = useQuery({
    queryKey: ["platform", "nps"],
    queryFn: async () => unwrap(await api.GET("/api/v1/platform/nps")),
  });
  const usage = useQuery({
    queryKey: ["platform", "usage", days],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/platform/usage", { params: { query: { days: Number(days) } } }),
      ),
  });
  const n = nps.data;
  const u = usage.data;
  return (
    <div className="max-w-6xl space-y-8">
      <h1 className="text-2xl font-semibold">{t("productInsights.title")}</h1>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">
          {t("productInsights.npsTitle", { days: n?.days ?? 90 })}
        </h2>
        {nps.isPending ? <Spinner label={t("grid.loading")} /> : null}
        {n ? (
          <>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {(
                [
                  ["nps", n.nps ?? "—"],
                  ["answers", n.answers],
                  ["promoters", n.promoters],
                  ["passives", n.passives],
                  ["detractors", n.detractors],
                  ["csat", n.csat_average ?? "—"],
                ] as const
              ).map(([key, value]) => (
                <div key={key} className="rounded-md border border-border p-3">
                  <dt className="text-sm text-muted-foreground">
                    {t(`productInsights.tiles.${key}`)}
                  </dt>
                  <dd className="text-xl font-semibold">{value}</dd>
                </div>
              ))}
            </dl>
            <div className="grid gap-6 md:grid-cols-2">
              <table className="text-sm">
                <caption className="text-left font-medium">{t("productInsights.byPlan")}</caption>
                <tbody>
                  {n.by_plan.map((row) => (
                    <tr key={row.plan} className="border-t border-border">
                      <th scope="row" className="p-2 text-left font-normal">
                        {row.plan || "—"}
                      </th>
                      <td className="p-2">{row.nps ?? "—"}</td>
                      <td className="p-2 text-muted-foreground">
                        {t("productInsights.answers", { count: row.answers })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <table className="text-sm">
                <caption className="text-left font-medium">{t("productInsights.byMonth")}</caption>
                <tbody>
                  {n.by_month.map((row) => (
                    <tr key={row.month} className="border-t border-border">
                      <th scope="row" className="p-2 text-left font-normal">
                        {row.month ? formatDate(row.month, locale) : "—"}
                      </th>
                      <td className="p-2">{row.nps ?? "—"}</td>
                      <td className="p-2 text-muted-foreground">
                        {t("productInsights.answers", { count: row.answers })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3 className="font-semibold">{t("productInsights.comments")}</h3>
            <ul className="space-y-2">
              {n.comments.map((c, i) => (
                <li key={i} className="rounded-md border border-border p-2 text-sm">
                  <p className="text-xs text-muted-foreground">
                    {c.organisation} · {c.score}/10 · {c.role} · {formatDate(c.created_at, locale)}
                  </p>
                  <p className="whitespace-pre-wrap">{c.comment}</p>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">{t("productInsights.usageTitle")}</h2>
        <p className="text-sm text-muted-foreground">{t("productInsights.usageExplain")}</p>
        <div className="w-40">
          <SelectField
            label={t("productInsights.window")}
            value={days}
            onChange={(e) => setDays(e.target.value)}
            options={["7", "30", "90"].map((d) => ({
              value: d,
              label: t("productInsights.days", { count: Number(d) }),
            }))}
          />
        </div>
        {u ? (
          <>
            <p className="text-sm">
              {t("productInsights.usageSummary", {
                events: u.events,
                people: u.people,
                organisations: u.organisations,
              })}
            </p>
            <div className="grid gap-6 md:grid-cols-2">
              <table className="text-sm">
                <caption className="text-left font-medium">
                  {t("productInsights.topEvents")}
                </caption>
                <thead>
                  <tr className="text-left">
                    <th scope="col" className="p-2">
                      {t("productInsights.event")}
                    </th>
                    <th scope="col" className="p-2">
                      {t("productInsights.count")}
                    </th>
                    <th scope="col" className="p-2">
                      {t("productInsights.people")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {u.top_events.map((row) => (
                    <tr key={row.name} className="border-t border-border">
                      <th scope="row" className="p-2 text-left font-normal">
                        {row.name}
                      </th>
                      <td className="p-2">{row.count}</td>
                      <td className="p-2">{row.people}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <table className="text-sm">
                <caption className="text-left font-medium">{t("productInsights.topPages")}</caption>
                <thead>
                  <tr className="text-left">
                    <th scope="col" className="p-2">
                      {t("productInsights.page")}
                    </th>
                    <th scope="col" className="p-2">
                      {t("productInsights.count")}
                    </th>
                    <th scope="col" className="p-2">
                      {t("productInsights.people")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {u.top_pages.map((row) => (
                    <tr key={row.route} className="border-t border-border">
                      <th scope="row" className="p-2 text-left font-normal">
                        {row.route || "/"}
                      </th>
                      <td className="p-2">{row.count}</td>
                      <td className="p-2">{row.people}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3 className="font-semibold">{t("productInsights.funnel")}</h3>
            <ol className="space-y-1 text-sm">
              {u.funnel.map((step) => {
                const first = u.funnel[0]?.organisations || 0;
                const share = first ? Math.round((step.organisations / first) * 100) : 0;
                return (
                  <li key={step.step} className="flex items-center gap-3">
                    <span className="w-48">{t(`productInsights.steps.${step.step}`)}</span>
                    <span className="w-16 font-medium">{step.organisations}</span>
                    <span className="text-muted-foreground">{share}%</span>
                  </li>
                );
              })}
            </ol>
          </>
        ) : null}
      </section>
    </div>
  );
}
