import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Button,
  DataGrid,
  PageHeader,
  PanelFooter,
  RuledPanel,
  SelectField,
  Spinner,
  Tabs,
  TextField,
  type ColumnDef,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { toDateInput } from "../calendar/dates";
import { useCursorList } from "../lists";
import { BillingOptions, BulkPayments, RunTutorReviews } from "../g3/BillingExtras";
import { BankReconciliation } from "../payments/BankReconciliation";
import { PaymentsList } from "../payments/PaymentsPages";
import { LateFeesTab, PackagesTab, PlansTab, SplitsTab } from "./Phase2Tabs";
import { EndHead, Figure, InvoiceStatus, PanelEmpty, PanelLoading, rowClass } from "./moneyUi";
import { useIsPhone } from "./useIsPhone";

type Tab =
  | "invoices"
  | "payments"
  | "charges"
  | "requests"
  | "runs"
  | "ageing"
  | "packages"
  | "plans"
  | "lateFees"
  | "splits"
  | "bank"
  | "record"
  | "options";
type InvoiceFilter = "draft" | "open" | "overdue" | "paid" | "all";
type Money = { amount: string; currency: string };
type Invoice = components["schemas"]["Invoice"];
type PaymentRequest = components["schemas"]["PaymentRequest"];
type Charge = components["schemas"]["Charge"];

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

function useGridLabels(empty?: string) {
  const { t } = useTranslation();
  return {
    loading: t("grid.loading"),
    empty: empty ?? t("grid.empty"),
    loadMore: t("grid.loadMore"),
  };
}

/** Invoices as a register: number, client, due date, total, what is still owed, status. */
export function InvoiceTable({
  rows,
  isLoading,
  hasMore,
  isFetchingMore,
  onLoadMore,
  empty,
  hideClient,
}: {
  rows: Invoice[];
  isLoading?: boolean;
  hasMore?: boolean;
  isFetchingMore?: boolean;
  onLoadMore?: () => void;
  empty?: string;
  /** On a client's own record the client column would repeat the page title. */
  hideClient?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const money = useMoney();
  const labels = useGridLabels(empty);
  const phone = useIsPhone();
  const columns = useMemo<ColumnDef<Invoice, unknown>[]>(
    () => [
      {
        id: "number",
        header: t("billing.number"),
        cell: ({ row }) => (
          <>
            <Link
              to="/invoices/$invoiceId"
              params={{ invoiceId: row.original.id }}
              className="font-medium whitespace-nowrap tabular-nums underline-offset-2 hover:underline"
            >
              {row.original.number || t("billing.draftInvoice")}
            </Link>
            {phone ? (
              <span className="block text-xs text-muted-foreground tabular-nums">
                {[
                  hideClient ? "" : row.original.client_name,
                  row.original.due_date
                    ? `${t("billing.due")} ${formatDate(row.original.due_date, i18n.language)}`
                    : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            ) : null}
          </>
        ),
      },
      { id: "client", header: t("billing.client"), cell: ({ row }) => row.original.client_name },
      {
        id: "due",
        header: t("billing.due"),
        cell: ({ row }) => (
          <span className="whitespace-nowrap">
            {row.original.due_date ? formatDate(row.original.due_date, i18n.language) : "—"}
          </span>
        ),
      },
      {
        id: "total",
        header: () => <EndHead>{t("billing.total")}</EndHead>,
        cell: ({ row }) => <Figure>{money(row.original.total)}</Figure>,
      },
      {
        id: "balance",
        header: () => <EndHead>{t("billing.balanceDue")}</EndHead>,
        cell: ({ row }) => <Figure strong>{money(row.original.balance_due)}</Figure>,
      },
      {
        id: "status",
        header: t("billing.statusLabel"),
        cell: ({ row }) => (
          <InvoiceStatus status={row.original.status} overdue={row.original.is_overdue} />
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- labels follow the language
    [t, i18n.language, phone, hideClient],
  );
  return (
    <DataGrid
      // On phones the client, due date and total fold into the number's context line.
      key={phone ? "phone" : "wide"}
      caption={t("billing.tabs.invoices")}
      rows={rows}
      columns={columns}
      getRowId={(r) => r.id}
      isLoading={isLoading}
      hasMore={hasMore}
      isFetchingMore={isFetchingMore}
      onLoadMore={onLoadMore}
      labels={labels}
      initialColumnVisibility={
        phone
          ? { client: false, due: false, total: false }
          : hideClient
            ? { client: false }
            : undefined
      }
    />
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
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SelectField
          label={t("billing.show")}
          hideLabel
          size="sm"
          value={filter}
          onChange={(e) => setFilter(e.target.value as InvoiceFilter)}
          options={(Object.keys(FILTERS) as InvoiceFilter[]).map((key) => ({
            value: key,
            label: t(`billing.filters.${key}`),
          }))}
        />
      </div>
      <InvoiceTable
        rows={list.rows}
        isLoading={list.query.isPending}
        hasMore={list.query.hasNextPage}
        isFetchingMore={list.query.isFetchingNextPage}
        onLoadMore={() => void list.query.fetchNextPage()}
        empty={t(`designS7.billing.empty.${filter}`)}
      />
    </div>
  );
}

function Charges() {
  const { t, i18n } = useTranslation();
  const money = useMoney();
  const labels = useGridLabels(t("designS7.billing.noCharges"));
  const phone = useIsPhone();
  const list = useCursorList(["charges", "uninvoiced"], async (cursor) =>
    unwrap(
      await api.GET("/api/v1/charges", { params: { query: { status: ["uninvoiced"], cursor } } }),
    ),
  );
  const columns = useMemo<ColumnDef<Charge, unknown>[]>(
    () => [
      {
        id: "date",
        header: t("billing.date"),
        cell: ({ row }) => (
          <span className="whitespace-nowrap">{formatDate(row.original.date, i18n.language)}</span>
        ),
      },
      { id: "client", header: t("billing.client"), cell: ({ row }) => row.original.client_name },
      {
        id: "description",
        header: t("billing.description"),
        cell: ({ row }) => (
          <>
            {row.original.description}
            {phone ? (
              <span className="block text-xs text-muted-foreground tabular-nums">
                {[
                  formatDate(row.original.date, i18n.language),
                  row.original.client_name,
                  row.original.student_name,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            ) : row.original.student_name ? (
              <span className="block text-xs text-muted-foreground">
                {row.original.student_name}
              </span>
            ) : null}
          </>
        ),
      },
      {
        id: "amount",
        header: () => <EndHead>{t("billing.amount")}</EndHead>,
        cell: ({ row }) => <Figure>{money(row.original.gross)}</Figure>,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- labels follow the language
    [t, i18n.language, phone],
  );
  return (
    <DataGrid
      key={phone ? "phone" : "wide"}
      initialColumnVisibility={phone ? { date: false, client: false } : undefined}
      caption={t("billing.tabs.charges")}
      rows={list.rows}
      columns={columns}
      getRowId={(r) => r.id}
      isLoading={list.query.isPending}
      hasMore={list.query.hasNextPage}
      isFetchingMore={list.query.isFetchingNextPage}
      onLoadMore={() => void list.query.fetchNextPage()}
      labels={labels}
    />
  );
}

/** Payment requests (credit top-ups) as a register. */
export function RequestTable({
  rows,
  isLoading,
  hasMore,
  isFetchingMore,
  onLoadMore,
}: {
  rows: PaymentRequest[];
  isLoading?: boolean;
  hasMore?: boolean;
  isFetchingMore?: boolean;
  onLoadMore?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const money = useMoney();
  const labels = useGridLabels(t("designS7.billing.noRequests"));
  const columns = useMemo<ColumnDef<PaymentRequest, unknown>[]>(
    () => [
      {
        id: "number",
        header: t("billing.number"),
        cell: ({ row }) => (
          <span className="font-medium whitespace-nowrap tabular-nums">{row.original.number}</span>
        ),
      },
      { id: "client", header: t("billing.client"), cell: ({ row }) => row.original.client_name },
      {
        id: "amount",
        header: () => <EndHead>{t("billing.amount")}</EndHead>,
        cell: ({ row }) => <Figure>{money(row.original.amount)}</Figure>,
      },
      {
        id: "status",
        header: t("billing.statusLabel"),
        cell: ({ row }) => t(`billing.requestStatus.${row.original.status}`),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- labels follow the language
    [t, i18n.language],
  );
  return (
    <DataGrid
      caption={t("billing.tabs.requests")}
      rows={rows}
      columns={columns}
      getRowId={(r) => r.id}
      isLoading={isLoading}
      hasMore={hasMore}
      isFetchingMore={isFetchingMore}
      onLoadMore={onLoadMore}
      labels={labels}
    />
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
    <div className="space-y-6">
      {canManage ? (
        <RuledPanel flush title={t("billing.bulkRequests")}>
          <form
            aria-label={t("billing.bulkRequests")}
            onSubmit={(e) => {
              e.preventDefault();
              bulk.mutate();
            }}
          >
            <div className="grid max-w-xl gap-3 px-5 py-4 sm:grid-cols-2">
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
            </div>
            <PanelFooter>
              <Button type="submit" variant="secondary" disabled={bulk.isPending}>
                {t("billing.bulkRequests")}
              </Button>
              {bulk.data ? (
                <p role="status" className="text-success">
                  {t("billing.requestsCreated", { count: bulk.data.created.length })}
                </p>
              ) : null}
            </PanelFooter>
          </form>
        </RuledPanel>
      ) : null}
      <ErrorList error={bulk.error} />
      <RequestTable
        rows={list.rows}
        isLoading={list.query.isPending}
        hasMore={list.query.hasNextPage}
        isFetchingMore={list.query.isFetchingNextPage}
        onLoadMore={() => void list.query.fetchNextPage()}
      />
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
    <div className="space-y-6">
      {canCreate ? (
        <RuledPanel flush title={t("billing.runInvoicing")}>
          <form
            aria-label={t("billing.runInvoicing")}
            onSubmit={(e) => {
              e.preventDefault();
              start.mutate();
            }}
          >
            <div className="grid gap-3 px-5 py-4 sm:grid-cols-2 lg:grid-cols-[repeat(2,minmax(0,12rem))_minmax(0,22rem)]">
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
            </div>
            <PanelFooter className="justify-between">
              <p className="tabular-nums" aria-live="polite">
                {preview.data
                  ? t("billing.previewResult", {
                      clients: preview.data.clients,
                      charges: preview.data.charges,
                    })
                  : null}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="secondary" onClick={() => preview.mutate()}>
                  {t("billing.preview")}
                </Button>
                <Button type="submit" disabled={start.isPending}>
                  {t("billing.runInvoicing")}
                </Button>
              </div>
            </PanelFooter>
          </form>
          {(start.error ?? preview.error) ? (
            <div className="px-5 pb-4">
              <ErrorList error={start.error ?? preview.error} />
            </div>
          ) : null}
        </RuledPanel>
      ) : null}
      <section
        aria-label={t("billing.tabs.runs")}
        className="rounded-xl border border-border bg-surface"
      >
        {runs.query.isPending ? (
          <PanelLoading label={t("grid.loading")} />
        ) : !runs.rows.length ? (
          <PanelEmpty>{t("designS7.billing.noRuns")}</PanelEmpty>
        ) : (
          <ul>
            {runs.rows.map((run) => {
              const stats = run.stats as { drafts?: number; held?: number; tutor_review?: boolean };
              const facts = [
                typeof stats.drafts === "number"
                  ? t("billing.drafts", { count: stats.drafts })
                  : "",
                typeof stats.held === "number"
                  ? t("g3.tutorReview.held", { count: stats.held })
                  : "",
              ].filter(Boolean);
              return (
                <li key={run.id} className={rowClass}>
                  <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                    <div className="min-w-0">
                      <p className="font-medium tabular-nums">
                        {formatDate(run.period_start, i18n.language)} –{" "}
                        {formatDate(run.period_end, i18n.language)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {t(`billing.modes.${run.mode}`)}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <div className="text-right">
                        <p>{t(`billing.runStatus.${run.status}`)}</p>
                        {facts.length ? (
                          <p className="text-xs text-muted-foreground tabular-nums">
                            {facts.join(" · ")}
                          </p>
                        ) : null}
                      </div>
                      {run.status === "review" && canIssue ? (
                        <Button size="sm" onClick={() => approve.mutate(run.id)}>
                          {t("billing.approveRun")}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                  {stats.tutor_review ? (
                    <details className="mt-2 text-sm">
                      <summary className="cursor-pointer font-medium text-link">
                        {t("g3.tutorReview.title")}
                      </summary>
                      <RunTutorReviews runId={run.id} />
                    </details>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <ErrorList error={approve.error} />
    </div>
  );
}

const BUCKETS = ["current", "one_to_30", "thirty_one_to_60", "sixty_one_to_90", "over_90"] as const;

function Ageing() {
  const { t } = useTranslation();
  const money = useMoney();
  const rows = useQuery({
    queryKey: ["ageing"],
    queryFn: async () => unwrap(await api.GET("/api/v1/billing/ageing")),
  });
  if (rows.isPending) return <Spinner label={t("grid.loading")} />;
  if (!rows.data?.length)
    return (
      <div className="rounded-xl border border-border bg-surface">
        <p className="px-4 py-10 text-center text-muted-foreground">
          {t("designS7.billing.noAgeing")}
        </p>
      </div>
    );
  const zero = (value: Money) => !/[1-9]/.test(value.amount);
  return (
    <div
      role="region"
      aria-label={t("billing.tabs.ageing")}
      tabIndex={0}
      className="relative overflow-x-auto rounded-xl border border-border bg-surface"
    >
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{t("billing.tabs.ageing")}</caption>
        <thead className="border-b border-border">
          <tr>
            <th scope="col" className="px-4 py-2.5 whitespace-nowrap">
              {t("billing.client")}
            </th>
            {BUCKETS.map((b) => (
              <th key={b} scope="col" className="w-32 px-4 py-2.5 text-right whitespace-nowrap">
                {t(`billing.ageing.${b}`)}
              </th>
            ))}
            <th scope="col" className="w-32 px-4 py-2.5 text-right whitespace-nowrap">
              {t("billing.total")}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.data.map((row) => (
            <tr key={row.client}>
              <td className="px-4 py-2.5">
                <Link
                  to="/clients/$clientId"
                  params={{ clientId: row.client }}
                  className="font-medium underline-offset-2 hover:underline"
                >
                  {row.client_name}
                </Link>
              </td>
              {BUCKETS.map((b) => (
                <td
                  key={b}
                  className={`px-4 py-2.5 text-right whitespace-nowrap ${
                    zero(row[b])
                      ? "text-muted-foreground"
                      : b === "current"
                        ? ""
                        : "font-medium text-margin"
                  }`}
                >
                  {money(row[b])}
                </td>
              ))}
              <td className="px-4 py-2.5 text-right font-semibold whitespace-nowrap">
                {money(row.total)}
              </td>
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
  const canPackages = usePermission("billing.package.view");
  const canPlans = usePermission("billing.plan.view");
  const canSplits = usePermission("billing.split.manage");
  const canBank = usePermission("payments.reconcile");
  const canRecord = usePermission("payments.payment.record");
  const canSettings = usePermission("billing.settings.manage");
  const tabs = [
    { key: "invoices" as const, label: t("billing.tabs.invoices") },
    ...(canPayments ? [{ key: "payments" as const, label: t("payments.title") }] : []),
    ...(canCharges ? [{ key: "charges" as const, label: t("billing.tabs.charges") }] : []),
    ...(canRequests ? [{ key: "requests" as const, label: t("billing.tabs.requests") }] : []),
    { key: "runs" as const, label: t("billing.tabs.runs") },
    { key: "ageing" as const, label: t("billing.tabs.ageing") },
    ...(canPackages ? [{ key: "packages" as const, label: t("packages.title") }] : []),
    ...(canPlans ? [{ key: "plans" as const, label: t("plans.title") }] : []),
    { key: "lateFees" as const, label: t("lateFees.tab") },
    ...(canSplits ? [{ key: "splits" as const, label: t("splits.title") }] : []),
    ...(canBank ? [{ key: "bank" as const, label: t("bank.title") }] : []),
    ...(canRecord ? [{ key: "record" as const, label: t("g3.bulkPayments.tab") }] : []),
    ...(canSettings ? [{ key: "options" as const, label: t("g3.billingOptions.tab") }] : []),
  ];
  const [tab, setTab] = useState<Tab>("invoices");
  return (
    <section>
      <PageHeader title={t("billing.title")} description={t("designS7.billing.description")} />
      <Tabs label={t("billing.title")} tabs={tabs} value={tab} onChange={setTab}>
        {tab === "invoices" ? <Invoices /> : null}
        {tab === "payments" ? <PaymentsList /> : null}
        {tab === "charges" ? <Charges /> : null}
        {tab === "requests" ? <Requests /> : null}
        {tab === "runs" ? <Runs /> : null}
        {tab === "ageing" ? <Ageing /> : null}
        {tab === "packages" ? <PackagesTab /> : null}
        {tab === "plans" ? <PlansTab /> : null}
        {tab === "lateFees" ? <LateFeesTab /> : null}
        {tab === "splits" ? <SplitsTab /> : null}
        {tab === "bank" ? <BankReconciliation /> : null}
        {tab === "record" ? <BulkPayments /> : null}
        {tab === "options" ? <BillingOptions /> : null}
      </Tabs>
    </section>
  );
}
