import { unwrap } from "@tutortrack/api-client";
import { formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

/** G6 (FR-30-7): revenue-share reconciliation: payments processed vs reported to the
 *  Stripe meter, per organisation and month, with a fix for unreported days. */
export function RevenueSharePage() {
  const { t } = useTranslation();
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
  const money = (amount: string, currency: string) => formatMoney({ amount, currency });
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("revenueShare.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("revenueShare.intro")}</p>
      <TextField
        label={t("revenueShare.month")}
        type="month"
        value={month}
        onChange={(e) => setMonth(e.target.value)}
      />
      {report.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      {report.data ? (
        <>
          <ul className="flex flex-wrap gap-4 text-sm">
            {Object.entries(report.data.totals).map(([currency, total]) => (
              <li key={currency} className="rounded-md border border-border p-3">
                <p className="font-medium">{currency}</p>
                <p>
                  {t("revenueShare.processed")}: {money(total.processed, currency)}
                </p>
                <p>
                  {t("revenueShare.expectedFee")}: {money(total.expected_fee, currency)}
                </p>
              </li>
            ))}
          </ul>
          {report.data.rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("revenueShare.none")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left">
                    <th scope="col">{t("revenueShare.organisation")}</th>
                    <th scope="col">{t("revenueShare.processed")}</th>
                    <th scope="col">{t("revenueShare.reported")}</th>
                    <th scope="col">{t("revenueShare.difference")}</th>
                    <th scope="col">{t("revenueShare.expectedFee")}</th>
                    <th scope="col">{t("revenueShare.state")}</th>
                  </tr>
                </thead>
                <tbody>
                  {report.data.rows.map((row) => (
                    <tr key={row.organisation_id} className="border-t border-border align-top">
                      <td>
                        {row.organisation_name}
                        <span className="block text-muted-foreground">{row.percent}%</span>
                      </td>
                      <td>{money(row.processed, row.currency)}</td>
                      <td>{money(row.reported, row.currency)}</td>
                      <td>{money(row.difference, row.currency)}</td>
                      <td>{money(row.expected_fee, row.currency)}</td>
                      <td>
                        {row.ok ? (
                          t("revenueShare.ok")
                        ) : (
                          <div className="space-y-1">
                            {row.unreported_days.length ? (
                              <p>
                                {t("revenueShare.unreported", {
                                  count: row.unreported_days.length,
                                })}
                              </p>
                            ) : null}
                            {row.changed_days.length ? (
                              <p>{t("revenueShare.changed", { count: row.changed_days.length })}</p>
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
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
      {fix.error ? <Alert tone="danger">{fix.error.message}</Alert> : null}
    </div>
  );
}
