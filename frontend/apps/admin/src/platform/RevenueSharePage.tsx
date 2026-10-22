import { unwrap } from "@tutortrack/api-client";
import { formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FigureStrip,
  figureCell,
  PageHeader,
  RuledTable,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

/** G6 (FR-30-7): revenue-share reconciliation: payments processed vs reported to the
 *  Stripe meter, per organisation and month, with a fix for unreported days. */
export function RevenueSharePage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [month, setMonth] = useState(thisMonth());
  const report = useQuery({
    queryKey: ["platform", "revenue-share", month],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/platform/revenue-share", { params: { query: { month } } })),
  });
  const fix = useMutation({
    mutationFn: async (organisationId: string) =>
      unwrap(
        await api.POST("/api/v1/platform/revenue-share/report-missing", {
          body: { organisation_id: organisationId, month },
        }),
      ),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["platform", "revenue-share"] }),
  });
  const money = (amount: string, currency: string) =>
    formatMoney({ amount, currency }, i18n.language);
  const totals = Object.entries(report.data?.totals ?? {});
  const several = totals.length > 1;
  const rows = report.data?.rows ?? [];
  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader
        title={t("revenueShare.title")}
        description={t("revenueShare.intro")}
        actions={
          <div className="w-44">
            <TextField
              label={t("revenueShare.month")}
              hideLabel
              size="sm"
              type="month"
              className="tabular-nums"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
            />
          </div>
        }
      />
      {totals.length ? (
        <FigureStrip
          label={t("revenueShare.title")}
          figures={totals.flatMap(([currency, total]) => [
            {
              key: `${currency}-processed`,
              label: several
                ? `${t("revenueShare.processed")} (${currency})`
                : t("revenueShare.processed"),
              value: money(total.processed, currency),
            },
            {
              key: `${currency}-fee`,
              label: several
                ? `${t("revenueShare.expectedFee")} (${currency})`
                : t("revenueShare.expectedFee"),
              value: money(total.expected_fee, currency),
            },
          ])}
        />
      ) : null}
      {fix.error ? <Alert tone="danger">{fix.error.message}</Alert> : null}
      <RuledTable
        framed
        caption={t("revenueShare.title")}
        loading={report.isPending}
        loadingLabel={t("grid.loading")}
        empty={report.data && !rows.length ? t("revenueShare.none") : undefined}
        columns={[
          { header: t("revenueShare.organisation") },
          { header: t("revenueShare.processed"), end: true, width: "w-32" },
          { header: t("revenueShare.reported"), end: true, width: "w-32" },
          { header: t("revenueShare.difference"), end: true, width: "w-32" },
          { header: t("revenueShare.expectedFee"), end: true, width: "w-32" },
          { header: t("revenueShare.state") },
        ]}
      >
        {rows.map((row) => (
          <tr key={row.organisation_id}>
            <td className="min-w-44">
              <span className="font-medium">{row.organisation_name}</span>
              <span className="block text-xs text-muted-foreground tabular-nums">
                {t("designS11.platform.sharePercent", { percent: row.percent })}
              </span>
            </td>
            <td className={figureCell}>{money(row.processed, row.currency)}</td>
            <td className={figureCell}>{money(row.reported, row.currency)}</td>
            <td className={figureCell}>{money(row.difference, row.currency)}</td>
            <td className={figureCell}>{money(row.expected_fee, row.currency)}</td>
            <td className="min-w-52">
              {row.ok ? (
                <span className="text-muted-foreground">{t("revenueShare.ok")}</span>
              ) : (
                <div className="space-y-1">
                  {row.unreported_days.length ? (
                    <p className="font-semibold text-margin">
                      {t("revenueShare.unreported", { count: row.unreported_days.length })}
                    </p>
                  ) : null}
                  {row.changed_days.length ? (
                    <p className="font-semibold text-margin">
                      {t("revenueShare.changed", { count: row.changed_days.length })}
                    </p>
                  ) : null}
                  {row.unreported_days.length ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={fix.isPending && fix.variables === row.organisation_id}
                      onClick={() => fix.mutate(row.organisation_id)}
                    >
                      {t("revenueShare.reportMissing")}
                    </Button>
                  ) : null}
                </div>
              )}
            </td>
          </tr>
        ))}
      </RuledTable>
    </div>
  );
}
