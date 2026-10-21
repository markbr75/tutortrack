import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, PanelFooter, RuledPanel, SelectField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";

type Connection = components["schemas"]["AccountingConnection"];

/** E23-T09: payments recorded directly in Xero or QuickBooks, read back as TutorTrack
 * payments (daily, or with "Check now"), with the ones that didn't fit. */
export function ReadBackSection({ conn, canManage }: { conn: Connection; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("");
  const provider = conn.provider_name;
  const imports = useQuery({
    queryKey: ["accounting", "payment-imports", status],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/accounting/payment-imports", {
          params: { query: status ? { status: status as "imported" | "skipped" } : {} },
        }),
      ),
  });
  const toggle = useMutation({
    mutationFn: async (value: boolean) =>
      unwrap(
        await api.PATCH("/api/v1/accounting/connections/{id}", {
          params: { path: { id: conn.id } },
          body: { import_payments: value },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["accounting"] }),
  });
  const check = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/accounting/connections/{id}/read-back", {
          params: { path: { id: conn.id } },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["accounting"] }),
  });
  const rows = imports.data?.results ?? [];
  return (
    <RuledPanel
      flush
      titleId="readback-heading"
      title={t("ledgerReadBack.title", { provider })}
      description={t("ledgerReadBack.help", { provider })}
    >
      <div className="space-y-3 px-5 py-4 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            className="size-4"
            disabled={!canManage || toggle.isPending}
            checked={Boolean(conn.import_payments)}
            onChange={(e) => toggle.mutate(e.target.checked)}
          />
          {t("ledgerReadBack.toggle", { provider })}
        </label>
        {conn.mode === "summary" ? (
          <Alert tone="info">{t("ledgerReadBack.summaryMode")}</Alert>
        ) : null}
        {conn.payments_checked_at ? (
          <p className="text-muted-foreground tabular-nums">
            {t("ledgerReadBack.lastChecked", { date: formatDateTime(conn.payments_checked_at) })}
          </p>
        ) : null}
        {(check.error ?? toggle.error) ? (
          <Alert tone="danger">{(check.error ?? toggle.error)?.message}</Alert>
        ) : null}
      </div>
      {(canManage && conn.import_payments && conn.enabled) || check.data ? (
        <PanelFooter className="border-border">
          {canManage && conn.import_payments && conn.enabled ? (
            <Button
              size="sm"
              variant="secondary"
              disabled={check.isPending}
              onClick={() => check.mutate()}
            >
              {t("ledgerReadBack.checkNow")}
            </Button>
          ) : null}
          {check.data ? (
            <p role="status" className="tabular-nums">
              {t("ledgerReadBack.result", {
                checked: check.data.checked,
                imported: check.data.imported,
                skipped: check.data.skipped,
              })}
            </p>
          ) : null}
        </PanelFooter>
      ) : null}
      <div className="border-t border-border px-5 py-3">
        <div className="w-56">
          <SelectField
            label={t("ledgerReadBack.show")}
            hideLabel
            size="sm"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            options={[
              { value: "", label: t("ledgerReadBack.all") },
              { value: "imported", label: t("ledgerReadBack.statuses.imported") },
              { value: "skipped", label: t("ledgerReadBack.statuses.skipped") },
            ]}
          />
        </div>
      </div>
      {imports.isLoading ? (
        <p role="status" className="px-5 pb-4 text-sm text-muted-foreground">
          {t("grid.loading")}
        </p>
      ) : null}
      {imports.data && rows.length === 0 ? (
        <p className="px-5 pb-5 text-sm text-muted-foreground">
          {t("ledgerReadBack.none", { provider })}
        </p>
      ) : null}
      {rows.length ? (
        <div
          role="region"
          aria-label={t("ledgerReadBack.title", { provider })}
          tabIndex={0}
          className="overflow-x-auto border-t border-rule"
        >
          <table className="w-full min-w-[40rem] text-sm">
            <caption className="sr-only">{t("ledgerReadBack.title", { provider })}</caption>
            <thead className="border-b border-border">
              <tr>
                <th scope="col" className="py-2.5 pr-4 pl-5">
                  {t("ledgerReadBack.paidOn")}
                </th>
                <th scope="col" className="px-4 py-2.5">
                  {t("ledgerReadBack.invoice")}
                </th>
                <th scope="col" className="px-4 py-2.5">
                  {t("ledgerReadBack.client")}
                </th>
                <th scope="col" className="w-32 px-4 py-2.5 text-right">
                  {t("ledgerReadBack.amount")}
                </th>
                <th scope="col" className="px-4 py-2.5">
                  {t("ledgerReadBack.reference")}
                </th>
                <th scope="col" className="py-2.5 pr-5 pl-4">
                  {t("ledgerReadBack.outcome")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="align-top">
                  <td className="py-2.5 pr-4 pl-5 whitespace-nowrap">
                    {row.paid_on ? formatDate(row.paid_on) : ""}
                  </td>
                  <td className="px-4 py-2.5">
                    <Link
                      to="/invoices/$invoiceId"
                      params={{ invoiceId: row.invoice }}
                      className="font-medium text-link underline-offset-2 hover:underline"
                    >
                      {row.invoice_number || t("ledgerReadBack.invoice")}
                    </Link>
                  </td>
                  <td className="px-4 py-2.5">{row.client_name}</td>
                  <td className="px-4 py-2.5 text-right whitespace-nowrap">
                    {formatMoney(row.amount)}
                  </td>
                  <td className="px-4 py-2.5">{row.reference}</td>
                  <td className="py-2.5 pr-5 pl-4">
                    {t(`ledgerReadBack.statuses.${row.status}`)}
                    {row.reason ? (
                      <div className="text-xs text-muted-foreground">{row.reason}</div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </RuledPanel>
  );
}
