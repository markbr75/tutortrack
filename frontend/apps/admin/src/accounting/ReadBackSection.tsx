import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner } from "@tutortrack/ui";
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
    <section className="space-y-3" aria-labelledby="readback-heading">
      <h2 id="readback-heading" className="text-lg font-semibold">
        {t("ledgerReadBack.title", { provider })}
      </h2>
      <p className="text-sm text-muted-foreground">{t("ledgerReadBack.help", { provider })}</p>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
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
        <p className="text-sm">
          {t("ledgerReadBack.lastChecked", { date: formatDateTime(conn.payments_checked_at) })}
        </p>
      ) : null}
      {canManage && conn.import_payments && conn.enabled ? (
        <Button variant="secondary" disabled={check.isPending} onClick={() => check.mutate()}>
          {t("ledgerReadBack.checkNow")}
        </Button>
      ) : null}
      {check.data ? (
        <p role="status" className="text-sm">
          {t("ledgerReadBack.result", {
            checked: check.data.checked,
            imported: check.data.imported,
            skipped: check.data.skipped,
          })}
        </p>
      ) : null}
      {(check.error ?? toggle.error) ? (
        <Alert tone="danger">{(check.error ?? toggle.error)?.message}</Alert>
      ) : null}
      <SelectField
        label={t("ledgerReadBack.show")}
        value={status}
        onChange={(e) => setStatus(e.target.value)}
        options={[
          { value: "", label: t("ledgerReadBack.all") },
          { value: "imported", label: t("ledgerReadBack.statuses.imported") },
          { value: "skipped", label: t("ledgerReadBack.statuses.skipped") },
        ]}
      />
      {imports.isLoading ? <Spinner className="size-4" label={t("grid.loading")} /> : null}
      {imports.data && rows.length === 0 ? (
        <p className="text-sm">{t("ledgerReadBack.none", { provider })}</p>
      ) : null}
      {rows.length ? (
        <table className="w-full text-sm">
          <caption className="sr-only">{t("ledgerReadBack.title", { provider })}</caption>
          <thead>
            <tr className="text-left">
              <th scope="col">{t("ledgerReadBack.paidOn")}</th>
              <th scope="col">{t("ledgerReadBack.invoice")}</th>
              <th scope="col">{t("ledgerReadBack.client")}</th>
              <th scope="col">{t("ledgerReadBack.amount")}</th>
              <th scope="col">{t("ledgerReadBack.reference")}</th>
              <th scope="col">{t("ledgerReadBack.outcome")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t border-border align-top">
                <td>{row.paid_on ? formatDate(row.paid_on) : ""}</td>
                <td>
                  <Link
                    to="/invoices/$invoiceId"
                    params={{ invoiceId: row.invoice }}
                    className="underline"
                  >
                    {row.invoice_number || t("ledgerReadBack.invoice")}
                  </Link>
                </td>
                <td>{row.client_name}</td>
                <td>{formatMoney(row.amount)}</td>
                <td>{row.reference}</td>
                <td>
                  {t(`ledgerReadBack.statuses.${row.status}`)}
                  {row.reason ? <div className="text-muted-foreground">{row.reason}</div> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
