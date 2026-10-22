import { unwrap } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  FigureStrip,
  figureCell,
  PageHeader,
  PanelRow,
  PanelRows,
  RuledPanel,
  RuledTable,
  SelectField,
  Spinner,
} from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

const PAIR = "grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-2";

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
  const first = u?.funnel[0]?.organisations || 0;
  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader title={t("productInsights.title")} />
      <section aria-labelledby="insights-nps" className="space-y-6">
        <h2 id="insights-nps" className="text-base font-semibold">
          {t("productInsights.npsTitle", { days: n?.days ?? 90 })}
        </h2>
        {nps.isPending ? <Spinner label={t("grid.loading")} /> : null}
        {n ? (
          <>
            <FigureStrip
              label={t("productInsights.npsTitle", { days: n.days })}
              columns={6}
              figures={(
                [
                  ["nps", n.nps ?? "–"],
                  ["answers", n.answers],
                  ["promoters", n.promoters],
                  ["passives", n.passives],
                  ["detractors", n.detractors],
                  ["csat", n.csat_average ?? "–"],
                ] as const
              ).map(([key, value]) => ({
                key,
                label: t(`productInsights.tiles.${key}`),
                value,
              }))}
            />
            <div className={PAIR}>
              <RuledPanel title={t("productInsights.byPlan")} flush>
                <RuledTable
                  caption={t("productInsights.byPlan")}
                  columns={[
                    { header: t("platform.plan") },
                    { header: t("productInsights.tiles.nps"), end: true },
                    { header: t("productInsights.tiles.answers"), end: true },
                  ]}
                >
                  {n.by_plan.map((row) => (
                    <tr key={row.plan}>
                      <th scope="row">{row.plan || "–"}</th>
                      <td className={figureCell}>{row.nps ?? "–"}</td>
                      <td className={`${figureCell} text-muted-foreground`}>
                        {t("productInsights.answers", { count: row.answers })}
                      </td>
                    </tr>
                  ))}
                </RuledTable>
              </RuledPanel>
              <RuledPanel title={t("productInsights.byMonth")} flush>
                <RuledTable
                  caption={t("productInsights.byMonth")}
                  columns={[
                    { header: t("saasMetrics.month") },
                    { header: t("productInsights.tiles.nps"), end: true },
                    { header: t("productInsights.tiles.answers"), end: true },
                  ]}
                >
                  {n.by_month.map((row) => (
                    <tr key={row.month}>
                      <th scope="row" className="tabular-nums">
                        {row.month ? formatDate(row.month, locale) : "–"}
                      </th>
                      <td className={figureCell}>{row.nps ?? "–"}</td>
                      <td className={`${figureCell} text-muted-foreground`}>
                        {t("productInsights.answers", { count: row.answers })}
                      </td>
                    </tr>
                  ))}
                </RuledTable>
              </RuledPanel>
            </div>
            <RuledPanel title={t("productInsights.comments")} flush>
              {n.comments.length ? (
                <PanelRows>
                  {n.comments.map((c, i) => (
                    <PanelRow key={i}>
                      <p className="text-xs text-muted-foreground tabular-nums">
                        <span className="font-medium text-foreground">{c.organisation}</span> ·{" "}
                        {c.score}/10 · {c.role} · {formatDate(c.created_at, locale)}
                      </p>
                      <p className="whitespace-pre-wrap">{c.comment}</p>
                    </PanelRow>
                  ))}
                </PanelRows>
              ) : (
                <p className="px-5 py-4 text-sm text-muted-foreground">
                  {t("designS11.platform.noComments")}
                </p>
              )}
            </RuledPanel>
          </>
        ) : null}
      </section>
      <section aria-labelledby="insights-usage" className="space-y-6 border-t border-border pt-6">
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
          <div className="min-w-0">
            <h2 id="insights-usage" className="text-base font-semibold">
              {t("productInsights.usageTitle")}
            </h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {t("productInsights.usageExplain")}
            </p>
          </div>
          <SelectField
            label={t("productInsights.window")}
            hideLabel
            size="sm"
            value={days}
            onChange={(e) => setDays(e.target.value)}
            options={["7", "30", "90"].map((d) => ({
              value: d,
              label: t("productInsights.days", { count: Number(d) }),
            }))}
          />
        </div>
        {usage.isPending ? <Spinner label={t("grid.loading")} /> : null}
        {u ? (
          <>
            <p className="text-sm tabular-nums">
              {t("productInsights.usageSummary", {
                events: u.events,
                people: u.people,
                organisations: u.organisations,
              })}
            </p>
            <div className={PAIR}>
              <RuledPanel title={t("productInsights.topEvents")} flush>
                <RuledTable
                  caption={t("productInsights.topEvents")}
                  columns={[
                    { header: t("productInsights.event") },
                    { header: t("productInsights.count"), end: true },
                    { header: t("productInsights.people"), end: true },
                  ]}
                >
                  {u.top_events.map((row) => (
                    <tr key={row.name}>
                      <th scope="row" className="font-mono text-xs leading-5 font-normal">
                        {row.name}
                      </th>
                      <td className={figureCell}>{row.count}</td>
                      <td className={figureCell}>{row.people}</td>
                    </tr>
                  ))}
                </RuledTable>
              </RuledPanel>
              <RuledPanel title={t("productInsights.topPages")} flush>
                <RuledTable
                  caption={t("productInsights.topPages")}
                  columns={[
                    { header: t("productInsights.page") },
                    { header: t("productInsights.count"), end: true },
                    { header: t("productInsights.people"), end: true },
                  ]}
                >
                  {u.top_pages.map((row) => (
                    <tr key={row.route}>
                      <th scope="row" className="font-mono text-xs leading-5 font-normal break-all">
                        {row.route || "/"}
                      </th>
                      <td className={figureCell}>{row.count}</td>
                      <td className={figureCell}>{row.people}</td>
                    </tr>
                  ))}
                </RuledTable>
              </RuledPanel>
            </div>
            <RuledPanel title={t("productInsights.funnel")} flush>
              <RuledTable
                caption={t("productInsights.funnel")}
                columns={[
                  { header: t("designS11.platform.step") },
                  { header: t("designS11.platform.organisations"), end: true },
                  { header: t("designS11.platform.ofSignedUp"), end: true },
                ]}
              >
                {u.funnel.map((step) => {
                  const share = first ? Math.round((step.organisations / first) * 100) : 0;
                  return (
                    <tr key={step.step}>
                      <th scope="row">{t(`productInsights.steps.${step.step}`)}</th>
                      <td className={figureCell}>{step.organisations}</td>
                      <td className={`${figureCell} text-muted-foreground`}>{share}%</td>
                    </tr>
                  );
                })}
              </RuledTable>
            </RuledPanel>
          </>
        ) : null}
      </section>
    </div>
  );
}
