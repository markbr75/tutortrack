import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { toDateInput } from "../calendar/dates";
import { useCursorList } from "../lists";
import { PaymentsList } from "../payments/PaymentsPages";
import { StatusBadge } from "./InvoicePage";

type Tab = "invoices" | "payments" | "charges" | "requests" | "runs" | "ageing";
type InvoiceFilter = "draft" | "open" | "overdue" | "paid" | "all";
type Money = { amount: string; currency: string };

const FILTERS: Record<InvoiceFilter, { status?: ("draft" | "issued" | "partially_paid" | "paid")[]; overdue?: boolean }> = {
  draft: { status: ["draft"] },
  open: { status: ["issued", "partially_paid"] },
  overdue: { overdue: true },
  paid: { status: ["paid"] },
  all: {},
}; // prettier-ignore

function useMoney() {
  const { i18n } = useTranslation();
  return (value: Money) => formatMoney(value, i18n.language);
}

export function InvoiceTable({ rows }: { rows: components["schemas"]["Invoice"][] }) {
  const { t, i18n } = useTranslation();
  const money = useMoney();
  if (!rows.length) return <p className="text-sm text-muted-foreground">{t("grid.empty")}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="py-2 pr-3">
              {t("billing.number")}
            </th>
            <th scope="col" className="py-2 pr-3">
              {t("billing.client")}
            </th>
            <th scope="col" className="py-2 pr-3">
              {t("billing.due")}
            </th>
            <th scope="col" className="py-2 pr-3 text-right">
              {t("billing.total")}
            </th>
            <th scope="col" className="py-2 pr-3 text-right">
              {t("billing.balanceDue")}
            </th>
            <th scope="col" className="py-2 pr-3">
              {t("billing.statusLabel")}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((inv) => (
            <tr key={inv.id} className="border-b border-border">
              <td className="py-2 pr-3">
                <Link
                  to="/invoices/$invoiceId"
                  params={{ invoiceId: inv.id }}
                  className="font-medium underline-offset-2 hover:underline"
                >
                  {inv.number || t("billing.draftInvoice")}
                </Link>
              </td>
              <td className="py-2 pr-3">{inv.client_name}</td>
              <td className="py-2 pr-3">
                {inv.due_date ? formatDate(inv.due_date, i18n.language) : "—"}
              </td>
              <td className="py-2 pr-3 text-right">{money(inv.total)}</td>
              <td className="py-2 pr-3 text-right">{money(inv.balance_due)}</td>
              <td className="py-2 pr-3">
                <StatusBadge status={inv.status} overdue={inv.is_overdue} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Invoices() {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<InvoiceFilter>("open");
  const list = useCursorList(["invoices", filter], async (cursor) =>
    unwrap(
      await api.GET("/api/v1/invoices", { params: { query: { ...FILTERS[filter], cursor } } }),
    ),
  );
  return (
    <div className="space-y-3">
      <SelectField
        label={t("billing.show")}
        value={filter}
        onChange={(e) => setFilter(e.target.value as InvoiceFilter)}
        options={(Object.keys(FILTERS) as InvoiceFilter[]).map((key) => ({
          value: key,
          label: t(`billing.filters.${key}`),
        }))}
      />
      {list.query.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : (
        <InvoiceTable rows={list.rows} />
      )}
      {list.query.hasNextPage ? (
        <Button size="sm" variant="ghost" onClick={() => void list.query.fetchNextPage()}>
          {t("grid.loadMore")}
        </Button>
      ) : null}
    </div>
  );
}

function Charges() {
  const { t, i18n } = useTranslation();
  const money = useMoney();
  const list = useCursorList(["charges", "uninvoiced"], async (cursor) =>
    unwrap(
      await api.GET("/api/v1/charges", { params: { query: { status: ["uninvoiced"], cursor } } }),
    ),
  );
  if (list.query.isPending) return <Spinner className="size-5" label={t("grid.loading")} />;
  if (!list.rows.length) return <p className="text-sm text-muted-foreground">{t("grid.empty")}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="py-2 pr-3">
              {t("billing.date")}
            </th>
            <th scope="col" className="py-2 pr-3">
              {t("billing.client")}
            </th>
            <th scope="col" className="py-2 pr-3">
              {t("billing.description")}
            </th>
            <th scope="col" className="py-2 pr-3 text-right">
              {t("billing.amount")}
            </th>
          </tr>
        </thead>
        <tbody>
          {list.rows.map((charge) => (
            <tr key={charge.id} className="border-b border-border">
              <td className="py-2 pr-3">{formatDate(charge.date, i18n.language)}</td>
              <td className="py-2 pr-3">{charge.client_name}</td>
              <td className="py-2 pr-3">
                {charge.description}
                {charge.student_name ? (
                  <span className="block text-muted-foreground">{charge.student_name}</span>
                ) : null}
              </td>
              <td className="py-2 pr-3 text-right">{money(charge.gross)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RequestTable({ rows }: { rows: components["schemas"]["PaymentRequest"][] }) {
  const { t } = useTranslation();
  const money = useMoney();
  if (!rows.length) return <p className="text-sm text-muted-foreground">{t("grid.empty")}</p>;
  return (
    <ul className="divide-y divide-border rounded-md border border-border text-sm">
      {rows.map((r) => (
        <li key={r.id} className="flex flex-wrap justify-between gap-2 p-3">
          <span>
            {r.number} · {r.client_name}
          </span>
          <span>
            {money(r.amount)} · {t(`billing.requestStatus.${r.status}`)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Requests() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("billing.payment_request.manage");
  const [form, setForm] = useState({ below: "50", top_up_to: "200", currency: "GBP" });
  const list = useCursorList(["payment-requests"], async (cursor) =>
    unwrap(await api.GET("/api/v1/payment-requests", { params: { query: { cursor } } })),
  );
  const bulk = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/payment-requests/bulk", {
          body: {
            below: { amount: form.below, currency: form.currency },
            top_up_to: { amount: form.top_up_to, currency: form.currency },
          },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["payment-requests"] }),
  });
  return (
    <div className="space-y-4">
      {canManage ? (
        <form
          className="flex flex-wrap items-end gap-2"
          aria-label={t("billing.bulkRequests")}
          onSubmit={(e) => {
            e.preventDefault();
            bulk.mutate();
          }}
        >
          <TextField
            type="number"
            label={t("billing.below")}
            value={form.below}
            onChange={(e) => setForm((f) => ({ ...f, below: e.target.value }))}
          />
          <TextField
            type="number"
            label={t("billing.topUpTo")}
            value={form.top_up_to}
            onChange={(e) => setForm((f) => ({ ...f, top_up_to: e.target.value }))}
          />
          <Button type="submit" variant="secondary" disabled={bulk.isPending}>
            {t("billing.bulkRequests")}
          </Button>
        </form>
      ) : null}
      {bulk.data ? (
        <Alert tone="success">
          {t("billing.requestsCreated", { count: bulk.data.created.length })}
        </Alert>
      ) : null}
      <ErrorList error={bulk.error} />
      {list.query.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : (
        <RequestTable rows={list.rows} />
      )}
    </div>
  );
}

function Runs() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canCreate = usePermission("billing.invoice.create");
  const canIssue = usePermission("billing.invoice.issue");
  const today = new Date();
  const monthAgo = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  const monthEnd = new Date(today.getFullYear(), today.getMonth(), 0);
  const [form, setForm] = useState({
    period_start: toDateInput(monthAgo),
    period_end: toDateInput(monthEnd),
    mode: "arrears" as "arrears" | "advance",
  });
  const runs = useCursorList(["invoice-runs"], async (cursor) =>
    unwrap(await api.GET("/api/v1/invoice-runs", { params: { query: { cursor } } })),
  );
  const preview = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/invoice-runs/preview", { body: form })),
  });
  const start = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/invoice-runs", { body: form })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["invoice-runs"] }),
  });
  const approve = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/invoice-runs/{id}/approve", { params: { path: { id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["invoice-runs"] }),
  });

  return (
    <div className="space-y-4">
      {canCreate ? (
        <form
          className="space-y-2"
          aria-label={t("billing.runInvoicing")}
          onSubmit={(e) => {
            e.preventDefault();
            start.mutate();
          }}
        >
          <div className="flex flex-wrap items-end gap-2">
            <TextField
              type="date"
              label={t("billing.periodStart")}
              value={form.period_start}
              onChange={(e) => setForm((f) => ({ ...f, period_start: e.target.value }))}
            />
            <TextField
              type="date"
              label={t("billing.periodEnd")}
              value={form.period_end}
              onChange={(e) => setForm((f) => ({ ...f, period_end: e.target.value }))}
            />
            <SelectField
              label={t("billing.mode")}
              value={form.mode}
              onChange={(e) =>
                setForm((f) => ({ ...f, mode: e.target.value as "arrears" | "advance" }))
              }
              options={[
                { value: "arrears", label: t("billing.modes.arrears") },
                { value: "advance", label: t("billing.modes.advance") },
              ]}
            />
            <Button type="button" variant="secondary" onClick={() => preview.mutate()}>
              {t("billing.preview")}
            </Button>
            <Button type="submit" disabled={start.isPending}>
              {t("billing.runInvoicing")}
            </Button>
          </div>
          {preview.data ? (
            <p className="text-sm" aria-live="polite">
              {t("billing.previewResult", {
                clients: preview.data.clients,
                charges: preview.data.charges,
              })}
            </p>
          ) : null}
          <ErrorList error={start.error ?? preview.error} />
        </form>
      ) : null}
      <ul className="divide-y divide-border rounded-md border border-border text-sm">
        {runs.rows.map((run) => (
          <li key={run.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
            <span>
              {formatDate(run.period_start, i18n.language)} –{" "}
              {formatDate(run.period_end, i18n.language)} · {t(`billing.modes.${run.mode}`)}
            </span>
            <span className="flex items-center gap-2">
              {t(`billing.runStatus.${run.status}`)}
              {typeof (run.stats as { drafts?: number }).drafts === "number"
                ? ` · ${t("billing.drafts", { count: (run.stats as { drafts: number }).drafts })}`
                : ""}
              {run.status === "review" && canIssue ? (
                <Button size="sm" onClick={() => approve.mutate(run.id)}>
                  {t("billing.approveRun")}
                </Button>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Ageing() {
  const { t } = useTranslation();
  const money = useMoney();
  const rows = useQuery({
    queryKey: ["ageing"],
    queryFn: async () => unwrap(await api.GET("/api/v1/billing/ageing")),
  });
  if (rows.isPending) return <Spinner className="size-5" label={t("grid.loading")} />;
  if (!rows.data?.length) return <p className="text-sm text-muted-foreground">{t("grid.empty")}</p>;
  const buckets = [
    "current",
    "one_to_30",
    "thirty_one_to_60",
    "sixty_one_to_90",
    "over_90",
  ] as const;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="py-2 pr-3">
              {t("billing.client")}
            </th>
            {buckets.map((b) => (
              <th key={b} scope="col" className="py-2 pr-3 text-right">
                {t(`billing.ageing.${b}`)}
              </th>
            ))}
            <th scope="col" className="py-2 pr-3 text-right">
              {t("billing.total")}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.data.map((row) => (
            <tr key={row.client} className="border-b border-border">
              <td className="py-2 pr-3">
                <Link to="/clients/$clientId" params={{ clientId: row.client }}>
                  {row.client_name}
                </Link>
              </td>
              {buckets.map((b) => (
                <td key={b} className="py-2 pr-3 text-right">
                  {money(row[b])}
                </td>
              ))}
              <td className="py-2 pr-3 text-right font-medium">{money(row.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The billing area (FR-10-14): invoices, uninvoiced charges, payment requests, invoice
 * runs and the ageing report. */
export function BillingPage() {
  const { t } = useTranslation();
  const canCharges = usePermission("billing.charge.view");
  const canRequests = usePermission("billing.payment_request.view");
  const canPayments = usePermission("payments.payment.view");
  const tabs = [
    { key: "invoices" as const, label: t("billing.tabs.invoices") },
    ...(canPayments ? [{ key: "payments" as const, label: t("payments.title") }] : []),
    ...(canCharges ? [{ key: "charges" as const, label: t("billing.tabs.charges") }] : []),
    ...(canRequests ? [{ key: "requests" as const, label: t("billing.tabs.requests") }] : []),
    { key: "runs" as const, label: t("billing.tabs.runs") },
    { key: "ageing" as const, label: t("billing.tabs.ageing") },
  ];
  const [tab, setTab] = useState<Tab>("invoices");
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("billing.title")}</h1>
      <Tabs label={t("billing.title")} tabs={tabs} value={tab} onChange={setTab}>
        {tab === "invoices" ? <Invoices /> : null}
        {tab === "payments" ? <PaymentsList /> : null}
        {tab === "charges" ? <Charges /> : null}
        {tab === "requests" ? <Requests /> : null}
        {tab === "runs" ? <Runs /> : null}
        {tab === "ageing" ? <Ageing /> : null}
      </Tabs>
    </div>
  );
}
