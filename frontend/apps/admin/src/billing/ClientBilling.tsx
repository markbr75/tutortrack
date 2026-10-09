import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { ClientPaymentMethods, RecordPayment } from "../payments/ClientPayments";
import { PaymentsList } from "../payments/PaymentsPages";
import { InvoiceTable, RequestTable } from "./BillingPage";

type Tab = "invoices" | "payments" | "methods" | "ledger" | "requests" | "charge";

/** The client's billing tab (FR-10-14): balances, invoices, ledger, payment requests and
 * one-off charges. */
export function ClientBilling({ clientId, currency }: { clientId: string; currency: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const canLedger = usePermission("billing.ledger.view");
  const canCharge = usePermission("billing.charge.create");
  const canInvoice = usePermission("billing.invoice.create");
  const canRequest = usePermission("billing.payment_request.manage");
  const canPayments = usePermission("payments.payment.view");
  const canRecord = usePermission("payments.payment.record");
  const [tab, setTab] = useState<Tab>("invoices");
  const [charge, setCharge] = useState({ description: "", amount: "" });
  const [request, setRequest] = useState("");
  const money = (value: { amount: string; currency: string }) => formatMoney(value, i18n.language);
  const path = { params: { path: { client_id: clientId } } };

  const balance = useQuery({
    queryKey: ["client", clientId, "balance"],
    queryFn: async () => unwrap(await api.GET("/api/v1/clients/{client_id}/balance", path)),
  });
  const invoices = useQuery({
    queryKey: ["invoices", "client", clientId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/invoices", { params: { query: { client: clientId } } })),
  });
  const ledger = useQuery({
    queryKey: ["client", clientId, "ledger"],
    enabled: tab === "ledger" && canLedger,
    queryFn: async () => unwrap(await api.GET("/api/v1/clients/{client_id}/ledger", path)),
  });
  const requests = useQuery({
    queryKey: ["payment-requests", "client", clientId],
    enabled: tab === "requests",
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/payment-requests", { params: { query: { client: clientId } } }),
      ),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["client", clientId] });
    void queryClient.invalidateQueries({ queryKey: ["invoices"] });
    void queryClient.invalidateQueries({ queryKey: ["payment-requests"] });
  };
  const addCharge = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/charges", {
          body: {
            client: clientId,
            description: charge.description,
            unit_price: { amount: charge.amount, currency },
            quantity: "1",
            category: "",
          },
        }),
      ),
    onSuccess: () => {
      setCharge({ description: "", amount: "" });
      refresh();
    },
  });
  const invoiceNow = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/invoices", { body: { client: clientId, until: null } })),
    onSuccess: (invoice) =>
      void navigate({ to: "/invoices/$invoiceId", params: { invoiceId: invoice.id } }),
  });
  const ask = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/payment-requests", {
          body: { client: clientId, amount: { amount: request, currency } },
        }),
      ),
    onSuccess: () => {
      setRequest("");
      setTab("requests");
      refresh();
    },
  });

  const b = balance.data;
  const tabs = [
    { key: "invoices" as const, label: t("billing.tabs.invoices") },
    ...(canPayments
      ? [
          { key: "payments" as const, label: t("payments.title") },
          { key: "methods" as const, label: t("payments.savedMethods") },
        ]
      : []),
    ...(canLedger ? [{ key: "ledger" as const, label: t("billing.ledger") }] : []),
    { key: "requests" as const, label: t("billing.tabs.requests") },
    ...(canCharge ? [{ key: "charge" as const, label: t("billing.addCharge") }] : []),
  ];

  return (
    <section aria-labelledby="client-billing" className="mt-6 space-y-4">
      <h2 id="client-billing" className="text-lg font-semibold">
        {t("billing.title")}
      </h2>
      {b ? (
        <dl className="grid gap-3 sm:grid-cols-4">
          {(
            [
              ["invoice_balance", t("billing.balances.owed")],
              ["overdue", t("billing.balances.overdue")],
              ["available_credit", t("billing.balances.credit")],
              ["uninvoiced", t("billing.balances.uninvoiced")],
            ] as const
          ).map(([key, label]) => (
            <div key={key} className="rounded-md border border-border p-3">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="text-lg font-semibold">{money(b[key])}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <Spinner className="size-5" label={t("grid.loading")} />
      )}
      <div className="flex flex-wrap gap-2">
        {canInvoice ? (
          <Button size="sm" variant="secondary" onClick={() => invoiceNow.mutate()}>
            {t("billing.invoiceNow")}
          </Button>
        ) : null}
        <a
          className="rounded-md border border-border px-3 py-1.5 text-sm"
          href={`/api/v1/clients/${clientId}/statement?pdf=true`}
          target="_blank"
          rel="noreferrer"
        >
          {t("billing.statement")}
        </a>
      </div>
      <ErrorList error={invoiceNow.error} />
      <Tabs label={t("billing.title")} tabs={tabs} value={tab} onChange={setTab}>
        {tab === "invoices" ? <InvoiceTable rows={invoices.data?.results ?? []} /> : null}
        {tab === "payments" ? (
          <div className="space-y-4">
            {canRecord ? (
              <RecordPayment clientId={clientId} currency={currency} onDone={refresh} />
            ) : null}
            <PaymentsList clientId={clientId} />
          </div>
        ) : null}
        {tab === "methods" ? <ClientPaymentMethods clientId={clientId} /> : null}
        {tab === "ledger" ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="py-2 pr-3">
                    {t("billing.date")}
                  </th>
                  <th scope="col" className="py-2 pr-3">
                    {t("billing.description")}
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right">
                    {t("billing.amount")}
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right">
                    {t("billing.runningBalance")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {(ledger.data ?? []).map((entry) => (
                  <tr key={entry.id} className="border-b border-border">
                    <td className="py-2 pr-3">{formatDate(entry.occurred_at, i18n.language)}</td>
                    <td className="py-2 pr-3">
                      {entry.description || t(`billing.entry.${entry.type}`)}
                    </td>
                    <td className="py-2 pr-3 text-right">{money(entry.amount)}</td>
                    <td className="py-2 pr-3 text-right">{money(entry.balance_after)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {tab === "requests" ? (
          <div className="space-y-3">
            {canRequest ? (
              <form
                className="flex flex-wrap items-end gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  ask.mutate();
                }}
              >
                <TextField
                  type="number"
                  step="0.01"
                  min={0}
                  label={t("billing.requestAmount")}
                  value={request}
                  required
                  onChange={(e) => setRequest(e.target.value)}
                />
                <Button type="submit" variant="secondary">
                  {t("billing.requestPayment")}
                </Button>
              </form>
            ) : null}
            <ErrorList error={ask.error} />
            <RequestTable rows={requests.data?.results ?? []} />
          </div>
        ) : null}
        {tab === "charge" ? (
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              addCharge.mutate();
            }}
          >
            <TextField
              label={t("billing.description")}
              value={charge.description}
              required
              onChange={(e) => setCharge((c) => ({ ...c, description: e.target.value }))}
            />
            <TextField
              type="number"
              step="0.01"
              label={t("billing.amount")}
              hint={t("billing.discountHint")}
              value={charge.amount}
              required
              onChange={(e) => setCharge((c) => ({ ...c, amount: e.target.value }))}
            />
            <Button type="submit" variant="secondary" disabled={addCharge.isPending}>
              {t("billing.addCharge")}
            </Button>
            {addCharge.isSuccess ? <Alert tone="success">{t("billing.chargeAdded")}</Alert> : null}
            <ErrorList error={addCharge.error} />
          </form>
        ) : null}
      </Tabs>
    </section>
  );
}
