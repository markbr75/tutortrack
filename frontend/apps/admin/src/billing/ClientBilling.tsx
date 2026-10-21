import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Button,
  buttonClass,
  FigureStrip,
  PanelFooter,
  RuledPanel,
  Spinner,
  Tabs,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { ClientPaymentMethods, RecordPayment } from "../payments/ClientPayments";
import { PackagesTab } from "./Phase2Tabs";
import { PaymentsList } from "../payments/PaymentsPages";
import { InvoiceTable, RequestTable } from "./BillingPage";

type Tab = "invoices" | "payments" | "methods" | "ledger" | "requests" | "charge" | "packages";

const owing = (amount: string) => /[1-9]/.test(amount) && !amount.startsWith("-");

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
  const canPackages = usePermission("billing.package.view");
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
    ...(canPackages ? [{ key: "packages" as const, label: t("packages.title") }] : []),
    ...(canCharge ? [{ key: "charge" as const, label: t("billing.addCharge") }] : []),
  ];

  const oldestOverdue = (invoices.data?.results ?? [])
    .filter((inv) => inv.is_overdue && inv.due_date)
    .map((inv) => inv.due_date as string)
    .sort()[0];
  return (
    <section aria-labelledby="client-billing" className="mt-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h2 id="client-billing" className="text-base font-semibold">
          {t("billing.title")}
        </h2>
        <div className="flex flex-wrap gap-2">
          <a
            className={buttonClass({ variant: "secondary", size: "sm" })}
            href={`/api/v1/clients/${clientId}/statement?pdf=true`}
            target="_blank"
            rel="noreferrer"
          >
            {t("billing.statement")}
          </a>
          {canInvoice ? (
            <Button size="sm" variant="secondary" onClick={() => invoiceNow.mutate()}>
              {t("billing.invoiceNow")}
            </Button>
          ) : null}
        </div>
      </div>
      {b ? (
        <FigureStrip
          label={t("billing.title")}
          figures={[
            { key: "owed", label: t("billing.balances.owed"), value: money(b.invoice_balance) },
            {
              key: "overdue",
              label: t("billing.balances.overdue"),
              value: money(b.overdue),
              // Say how long it has waited when the oldest overdue invoice is on this page.
              note: owing(b.overdue.amount)
                ? oldestOverdue
                  ? t("designS7.billing.overdueSince", {
                      date: formatDate(oldestOverdue, i18n.language),
                    })
                  : undefined
                : t("designS7.billing.nothingOverdue"),
              tone: owing(b.overdue.amount) ? "margin" : "default",
            },
            {
              key: "credit",
              label: t("billing.balances.credit"),
              value: money(b.available_credit),
            },
            {
              key: "uninvoiced",
              label: t("billing.balances.uninvoiced"),
              value: money(b.uninvoiced),
            },
          ]}
        />
      ) : (
        <Spinner label={t("grid.loading")} />
      )}
      <ErrorList error={invoiceNow.error} />
      <Tabs label={t("billing.title")} tabs={tabs} value={tab} onChange={setTab}>
        {tab === "invoices" ? (
          <InvoiceTable
            rows={invoices.data?.results ?? []}
            isLoading={invoices.isPending}
            empty={t("designS7.billing.empty.all")}
            hideClient
          />
        ) : null}
        {tab === "payments" ? (
          <div className="space-y-6">
            {canRecord ? (
              <RecordPayment clientId={clientId} currency={currency} onDone={refresh} />
            ) : null}
            <PaymentsList clientId={clientId} />
          </div>
        ) : null}
        {tab === "methods" ? <ClientPaymentMethods clientId={clientId} /> : null}
        {tab === "packages" ? <PackagesTab clientId={clientId} /> : null}
        {tab === "ledger" ? (
          <div
            role="region"
            aria-label={t("billing.ledger")}
            tabIndex={0}
            className="relative overflow-x-auto rounded-xl border border-border bg-surface"
          >
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{t("billing.ledger")}</caption>
              <thead className="border-b border-border">
                <tr>
                  <th scope="col" className="w-32 px-4 py-2.5">
                    {t("billing.date")}
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    {t("billing.description")}
                  </th>
                  <th scope="col" className="w-32 px-4 py-2.5 text-right">
                    {t("billing.amount")}
                  </th>
                  <th scope="col" className="w-32 px-4 py-2.5 text-right">
                    {t("billing.runningBalance")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {ledger.isPending ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-3">
                      <Spinner className="sr-only" label={t("grid.loading")} />
                      <div aria-hidden="true" className="h-4 animate-pulse rounded bg-muted" />
                    </td>
                  </tr>
                ) : !(ledger.data ?? []).length ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-10 text-center text-muted-foreground">
                      {t("grid.empty")}
                    </td>
                  </tr>
                ) : (
                  (ledger.data ?? []).map((entry) => (
                    <tr key={entry.id}>
                      <td className="px-4 py-2.5 whitespace-nowrap">
                        {formatDate(entry.occurred_at, i18n.language)}
                      </td>
                      <td className="px-4 py-2.5">
                        {entry.description || t(`billing.entry.${entry.type}`)}
                      </td>
                      <td className="px-4 py-2.5 text-right whitespace-nowrap">
                        {money(entry.amount)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-medium whitespace-nowrap">
                        {money(entry.balance_after)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        ) : null}
        {tab === "requests" ? (
          <div className="space-y-6">
            {canRequest ? (
              <form
                className="flex flex-wrap items-end gap-2"
                aria-label={t("billing.requestPayment")}
                onSubmit={(e) => {
                  e.preventDefault();
                  ask.mutate();
                }}
              >
                <div className="w-40">
                  <TextField
                    type="number"
                    step="0.01"
                    min={0}
                    label={t("billing.requestAmount")}
                    value={request}
                    required
                    onChange={(e) => setRequest(e.target.value)}
                  />
                </div>
                <Button type="submit" variant="secondary">
                  {t("billing.requestPayment")}
                </Button>
              </form>
            ) : null}
            <ErrorList error={ask.error} />
            <RequestTable rows={requests.data?.results ?? []} isLoading={requests.isPending} />
          </div>
        ) : null}
        {tab === "charge" ? (
          <RuledPanel flush>
            <form
              aria-label={t("billing.addCharge")}
              onSubmit={(e) => {
                e.preventDefault();
                addCharge.mutate();
              }}
            >
              <div className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_12rem]">
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
              </div>
              <PanelFooter>
                <Button type="submit" variant="secondary" disabled={addCharge.isPending}>
                  {t("billing.addCharge")}
                </Button>
                {addCharge.isSuccess ? (
                  <p role="status" className="text-success">
                    {t("billing.chargeAdded")}
                  </p>
                ) : null}
              </PanelFooter>
              {addCharge.error ? (
                <div className="px-5 pb-4">
                  <ErrorList error={addCharge.error} />
                </div>
              ) : null}
            </form>
          </RuledPanel>
        ) : null}
      </Tabs>
    </section>
  );
}
