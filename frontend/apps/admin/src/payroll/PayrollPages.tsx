import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  DataGrid,
  PageHeader,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
  type ColumnDef,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useMemo, useState, type ReactNode } from "react";

import { api, usePermission } from "../api";
import { BackTrail } from "../components/RecordHeader";
import { EndHead, Figure, PanelEmpty, PanelLoading, rowClass } from "../billing/moneyUi";
import { useIsPhone } from "../billing/useIsPhone";
import { withoutIsoDate } from "./describe";
import { RunItems } from "../g3/PayrollExtras";
import { WiseConnectionCard } from "./PayPhase3";

type Totals = Record<string, string>;
type PayRunRow = components["schemas"]["PayRun"];
type PayItem = components["schemas"]["PayItem"];

function totals(values: Totals | undefined): string {
  const entries = Object.entries(values ?? {});
  return entries.length
    ? entries.map(([currency, amount]) => formatMoney({ amount, currency })).join(" + ")
    : "–";
}

/** The payroll area's own sub-navigation, ruled like a tab row. */
export function PayrollNav() {
  const { t } = useTranslation();
  const links = [
    { to: "/payroll", label: t("payroll.runs") },
    { to: "/payroll/expenses", label: t("payroll.expenses") },
    { to: "/payroll/items", label: t("payroll.items") },
    { to: "/payroll/tax-forms", label: t("payrollPhase3.taxFormsNav") },
  ] as const;
  return (
    <nav
      aria-label={t("payroll.title")}
      className="relative mb-5 flex gap-1 overflow-x-auto border-b border-border pr-6 [mask-image:linear-gradient(to_right,black_calc(100%-1.5rem),transparent)] [scrollbar-width:none]"
    >
      {links.map((l) => (
        <Link
          key={l.to}
          to={l.to}
          activeOptions={{ exact: true }}
          className="-mb-px shrink-0 border-b-2 border-transparent px-3 py-2 text-sm whitespace-nowrap text-muted-foreground hover:text-foreground [&.active]:border-foreground [&.active]:font-semibold [&.active]:text-foreground"
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}

function Page({
  title,
  description,
  actions,
  back = false,
  children,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  /** A record inside Payroll: a back link instead of the section tabs (none would be current). */
  back?: boolean;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <section className="max-w-6xl">
      {back ? (
        <BackTrail>
          <Link to="/payroll">{t("payroll.title")}</Link>
        </BackTrail>
      ) : null}
      <PageHeader title={title} description={description} actions={actions} />
      {back ? null : <PayrollNav />}
      <div className="space-y-6">{children}</div>
    </section>
  );
}

function useGridLabels(empty?: string) {
  const { t } = useTranslation();
  return {
    loading: t("grid.loading"),
    empty: empty ?? t("grid.empty"),
    loadMore: t("grid.loadMore"),
  };
}

/** Pay runs (FR-12-5): list and open a new one for a period. */
export function PayRunsPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canCreate = usePermission("payroll.payrun.create");
  const today = new Date().toISOString().slice(0, 10);
  const monthAgo = new Date(Date.now() - 30 * 86_400_000).toISOString().slice(0, 10);
  const [start, setStart] = useState(monthAgo);
  const [end, setEnd] = useState(today);
  const runs = useQuery({
    queryKey: ["pay-runs"],
    queryFn: async () => unwrap(await api.GET("/api/v1/pay-runs")),
  });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/pay-runs", { body: { period_start: start, period_end: end } }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["pay-runs"] }),
  });
  const labels = useGridLabels(t("designS7.payroll.noRuns"));
  const phone = useIsPhone();
  const columns = useMemo<ColumnDef<PayRunRow, unknown>[]>(
    () => [
      {
        id: "number",
        header: t("payroll.number"),
        cell: ({ row }) => (
          <>
            <Link
              to="/payroll/runs/$id"
              params={{ id: row.original.id }}
              className="font-medium whitespace-nowrap tabular-nums underline-offset-2 hover:underline"
            >
              {row.original.number}
            </Link>
            {phone ? (
              <span className="block text-xs text-muted-foreground tabular-nums">
                {formatDate(row.original.period_start, i18n.language)} –{" "}
                {formatDate(row.original.period_end, i18n.language)} ·{" "}
                {t(`payroll.runStatus.${row.original.status}`)}
              </span>
            ) : null}
          </>
        ),
      },
      {
        id: "period",
        header: t("payroll.period"),
        cell: ({ row }) => (
          <span className="whitespace-nowrap">
            {formatDate(row.original.period_start, i18n.language)} –{" "}
            {formatDate(row.original.period_end, i18n.language)}
          </span>
        ),
      },
      {
        id: "status",
        header: t("payroll.status"),
        cell: ({ row }) => t(`payroll.runStatus.${row.original.status}`),
      },
      {
        id: "total",
        header: () => <EndHead>{t("payroll.total")}</EndHead>,
        cell: ({ row }) => <Figure strong>{totals(row.original.totals as Totals)}</Figure>,
      },
    ],
    [t, i18n.language, phone],
  );
  return (
    <Page title={t("payroll.title")}>
      <div>
        {canCreate ? (
          <form
            aria-label={t("payroll.newRun")}
            className="mb-4 flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <TextField
              size="sm"
              label={t("payroll.periodStart")}
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
            <TextField
              size="sm"
              label={t("payroll.periodEnd")}
              type="date"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
            <Button type="submit" className="h-9" loading={create.isPending}>
              {t("payroll.newRun")}
            </Button>
          </form>
        ) : null}
        {create.error ? (
          <Alert tone="danger" className="mb-4">
            {create.error.message}
          </Alert>
        ) : null}
        <DataGrid
          // On phones the period and status fold into the number's context line.
          key={phone ? "phone" : "wide"}
          initialColumnVisibility={phone ? { period: false, status: false } : undefined}
          caption={t("payroll.runs")}
          rows={runs.data?.results ?? []}
          columns={columns}
          getRowId={(r) => r.id}
          isLoading={runs.isPending}
          labels={labels}
        />
      </div>
      <WiseConnectionCard />
    </Page>
  );
}

type PayRun = components["schemas"]["PayRunDetail"];

/** Review, approve, pay and download (FR-12-5..8). */
export function PayRunPage({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canApprove = usePermission("payroll.payrun.approve");
  const canPay = usePermission("payroll.payrun.pay");
  const [format, setFormat] = useState("");
  const run = useQuery({
    queryKey: ["pay-run", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/pay-runs/{id}", { params: { path: { id } } })),
    refetchInterval: (query) => (query.state.data?.status === "draft" ? 2000 : false),
  });
  const path = { params: { path: { id } } };
  const done = (data: PayRun) => queryClient.setQueryData(["pay-run", id], data);
  const approve = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/pay-runs/{id}/approve", path)),
    onSuccess: done,
  });
  const cancel = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/pay-runs/{id}/cancel", path)),
    onSuccess: done,
  });
  const markPaid = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/pay-runs/{id}/mark-paid", { ...path, body: { reference: "" } }),
      ),
    onSuccess: done,
  });
  const bankFile = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/pay-runs/{id}/bank-files", {
          ...path,
          body: format ? { format: format as "csv" } : {},
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["pay-run", id] }),
  });
  if (!run.data) return <Spinner label={t("grid.loading")} />;
  const r = run.data;
  const paying = r.status === "approved" || r.status === "paying";
  const error = approve.error ?? cancel.error ?? markPaid.error ?? bankFile.error;
  const runTotals = Object.entries((r.totals as Totals) ?? {});
  return (
    <Page
      back
      title={`${t("payroll.run")} ${r.number}`}
      description={
        <span className="tabular-nums">
          {formatDate(r.period_start, i18n.language)} – {formatDate(r.period_end, i18n.language)} ·{" "}
          {t(`payroll.runStatus.${r.status}`)}
        </span>
      }
      actions={
        <>
          {["review", "approved"].includes(r.status) ? (
            <Button size="sm" variant="ghost" onClick={() => cancel.mutate()}>
              {t("payroll.cancelRun")}
            </Button>
          ) : null}
          {r.status === "review" && canApprove ? (
            <Button onClick={() => approve.mutate()} loading={approve.isPending}>
              {t("payroll.approve")}
            </Button>
          ) : null}
        </>
      }
    >
      {(r.warnings as { code: string; message: string }[]).length ||
      r.approvals_required > 1 ||
      error ? (
        <div className="space-y-3">
          {(r.warnings as { code: string; message: string }[]).map((w, i) => (
            <Alert key={i} tone="warning">
              {w.message}
            </Alert>
          ))}
          {r.approvals_required > 1 ? (
            <p className="text-sm tabular-nums">
              {t("payroll.approvals", {
                count: (r.approvals as unknown[]).length,
                required: r.approvals_required,
              })}
            </p>
          ) : null}
          {error ? <Alert tone="danger">{error.message}</Alert> : null}
        </div>
      ) : null}

      <section aria-labelledby="payouts-h" className="rounded-xl border border-border bg-surface">
        <div className="flex items-baseline justify-between gap-3 border-b border-border px-5 py-3.5">
          <h2 id="payouts-h" className="text-base font-semibold">
            {t("designS7.payroll.payouts")}
          </h2>
          <span className="text-sm text-muted-foreground tabular-nums">
            {t("designS7.payroll.payoutCount", { count: r.payouts.length })}
          </span>
        </div>
        <div
          role="region"
          aria-labelledby="payouts-h"
          tabIndex={0}
          className="relative overflow-x-auto"
        >
          <table className="w-full text-left text-sm md:min-w-[36rem]">
            <caption className="sr-only">{t("designS7.payroll.payouts")}</caption>
            <thead className="border-b border-border">
              <tr>
                <th scope="col" className="py-2.5 pr-4 pl-5">
                  {t("payroll.tutor")}
                </th>
                <th scope="col" className="px-4 py-2.5 max-md:hidden">
                  {t("payroll.method")}
                </th>
                <th scope="col" className="px-4 py-2.5">
                  {t("payroll.status")}
                </th>
                <th scope="col" className="px-4 py-2.5 max-md:hidden">
                  {t("payroll.statement")}
                </th>
                <th scope="col" className="w-32 py-2.5 pr-5 pl-4 text-right">
                  {t("payroll.amount")}
                </th>
              </tr>
            </thead>
            <tbody>
              {r.payouts.map((p) => (
                <tr key={p.id}>
                  <td className="py-2.5 pr-4 pl-5">
                    <span className="font-medium">{p.tutor_name}</span>
                    {/* On phones the method and statement fold into the tutor's context line. */}
                    <span className="block text-xs text-muted-foreground md:hidden">
                      {t(`payroll.methods.${p.method}`)}
                      {p.statement ? (
                        <>
                          {" · "}
                          <a
                            className="text-link tabular-nums underline-offset-2 hover:underline"
                            href={`/api/v1/pay-statements/${p.statement.id}/pdf`}
                          >
                            {p.statement.number}
                          </a>
                        </>
                      ) : null}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 max-md:hidden">{t(`payroll.methods.${p.method}`)}</td>
                  <td className="px-4 py-2.5">
                    <span className={p.status === "failed" ? "font-medium text-danger" : ""}>
                      {t(`payroll.payoutStatus.${p.status}`)}
                    </span>
                    {p.failure_reason ? (
                      <span className="block text-xs text-muted-foreground">
                        {p.failure_reason}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-2.5 max-md:hidden">
                    {p.statement ? (
                      <a
                        className="text-link tabular-nums underline-offset-2 hover:underline"
                        href={`/api/v1/pay-statements/${p.statement.id}/pdf`}
                      >
                        {p.statement.number}
                      </a>
                    ) : (
                      <span className="text-muted-foreground">–</span>
                    )}
                  </td>
                  <td className="py-2.5 pr-5 pl-4 text-right">{formatMoney(p.amount)}</td>
                </tr>
              ))}
              {!r.payouts.length ? (
                <tr>
                  <td colSpan={5} className="px-5 py-6 text-muted-foreground">
                    {t("designS7.payroll.noPayouts")}
                  </td>
                </tr>
              ) : null}
            </tbody>
            <tfoot>
              {(runTotals.length ? runTotals : [["", ""]]).map(([currency, amount], i) => (
                <tr key={currency || "none"} className={i === 0 ? "border-t border-border" : ""}>
                  <th
                    scope="row"
                    colSpan={4}
                    className="py-3 pr-4 pl-5 text-right text-base font-semibold max-md:hidden"
                  >
                    {i === 0 ? t("payroll.total") : ""}
                  </th>
                  <th
                    scope="row"
                    colSpan={2}
                    className="py-3 pr-4 pl-5 text-right text-base font-semibold md:hidden"
                  >
                    {i === 0 ? t("payroll.total") : ""}
                  </th>
                  <td className="py-3 pr-5 pl-4 text-right text-base font-semibold">
                    {currency ? formatMoney({ amount: amount!, currency }) : "–"}
                  </td>
                </tr>
              ))}
            </tfoot>
          </table>
        </div>
      </section>

      {(paying && canPay) || r.bank_files.length ? (
        <RuledPanel
          flush
          title={t("designS7.payroll.bankFiles")}
          footer={
            paying && canPay ? (
              <>
                <div className="w-44">
                  <SelectField
                    size="sm"
                    label={t("payroll.fileFormat")}
                    hideLabel
                    value={format}
                    onChange={(e) => setFormat(e.target.value)}
                    options={[
                      { value: "", label: t("designS7.payroll.defaultFormat") },
                      ...["csv", "bacs18", "sepa", "nacha", "aba"].map((f) => ({
                        value: f,
                        label: f.toUpperCase(),
                      })),
                    ]}
                  />
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  className="h-9"
                  onClick={() => bankFile.mutate()}
                >
                  {t("payroll.makeBankFile")}
                </Button>
                <Button className="ml-auto" onClick={() => markPaid.mutate()}>
                  {t("payroll.markPaid")}
                </Button>
              </>
            ) : undefined
          }
        >
          {r.bank_files.length ? (
            <ul className="text-sm">
              {r.bank_files.map((f) => (
                <li key={f.id} className={`${rowClass} flex justify-between gap-4`}>
                  <a
                    className="font-medium text-link underline-offset-2 hover:underline"
                    href={`/api/v1/pay-runs/${id}/bank-files/${f.id}`}
                  >
                    {f.filename}
                  </a>
                  <span className="text-muted-foreground tabular-nums">
                    {t("designS7.payroll.payoutCount", { count: f.payout_count })}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <PanelEmpty>{t("designS7.payroll.noBankFiles")}</PanelEmpty>
          )}
        </RuledPanel>
      ) : null}

      <RunItems runId={id} editable={r.status === "review"} />

      <p className="border-t border-border pt-4 text-sm">
        <span className="text-muted-foreground">{t("payroll.exportFor")}</span>{" "}
        {["xero", "quickbooks", "brightpay", "gusto", "generic"].map((f) => (
          <a
            key={f}
            className="mr-3 font-medium text-link underline-offset-2 hover:underline"
            href={`/api/v1/pay-runs/${id}/payroll-export?format=${f}`}
          >
            {t(`payroll.exports.${f}`)}
          </a>
        ))}
      </p>
    </Page>
  );
}

/** Claims waiting for approval (FR-12-4). */
export function ExpensesPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [comment, setComment] = useState<Record<string, string>>({});
  const claims = useQuery({
    queryKey: ["expenses", "submitted"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/expenses", { params: { query: { status: "submitted" } } })),
  });
  const decide = useMutation({
    mutationFn: async ({ id, verdict }: { id: string; verdict: "approve" | "reject" }) => {
      const options = { params: { path: { id } }, body: { comment: comment[id] ?? "" } };
      return verdict === "approve"
        ? unwrap(await api.POST("/api/v1/expenses/{id}/approve", options))
        : unwrap(await api.POST("/api/v1/expenses/{id}/reject", options));
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["expenses"] }),
  });
  const rows = claims.data?.results ?? [];
  return (
    <Page title={t("payroll.expenses")}>
      <section
        aria-label={t("payroll.expenses")}
        className="rounded-xl border border-border bg-surface text-sm"
      >
        {claims.isPending ? (
          <PanelLoading label={t("grid.loading")} />
        ) : !rows.length ? (
          <PanelEmpty>{t("payroll.noClaims")}</PanelEmpty>
        ) : (
          <ul>
            {rows.map((claim) => (
              <li key={claim.id} className={`${rowClass} space-y-2 py-3`}>
                <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                  <div className="min-w-0">
                    <p className="font-medium">{claim.tutor_name}</p>
                    <p className="text-xs text-muted-foreground tabular-nums">
                      {claim.category_name} · {formatDate(claim.date, i18n.language)}
                      {claim.rebillable ? ` · ${t("payroll.rebillable")}` : ""}
                    </p>
                  </div>
                  <span className="font-semibold tabular-nums">{formatMoney(claim.amount)}</span>
                </div>
                {claim.description ? <p>{claim.description}</p> : null}
                {claim.receipt ? (
                  <a
                    className="inline-block font-medium text-link underline-offset-2 hover:underline"
                    href={`/api/v1/files/${claim.receipt}/download`}
                  >
                    {t("payroll.receipt")}
                  </a>
                ) : null}
                <div className="flex flex-wrap items-end gap-2">
                  <div className="min-w-48 flex-1 sm:max-w-sm">
                    <TextField
                      size="sm"
                      label={t("payroll.comment")}
                      value={comment[claim.id] ?? ""}
                      onChange={(e) => setComment({ ...comment, [claim.id]: e.target.value })}
                    />
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-9"
                    onClick={() => decide.mutate({ id: claim.id, verdict: "reject" })}
                  >
                    {t("payroll.rejectClaim")}
                  </Button>
                  <Button
                    size="sm"
                    className="h-9"
                    onClick={() => decide.mutate({ id: claim.id, verdict: "approve" })}
                  >
                    {t("payroll.approveClaim")}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      {decide.error ? <Alert tone="danger">{decide.error.message}</Alert> : null}
    </Page>
  );
}

/** All pay items, with holds (FR-12-1). */
export function PayItemsPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("payroll.item.manage");
  const [status, setStatus] = useState("held");
  const items = useQuery({
    queryKey: ["pay-items", status],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/pay-items", { params: { query: { status } } })),
  });
  const act = useMutation({
    mutationFn: async ({ id, kind }: { id: string; kind: "release" | "void" }) =>
      kind === "release"
        ? unwrap(await api.POST("/api/v1/pay-items/{id}/release", { params: { path: { id } } }))
        : unwrap(await api.POST("/api/v1/pay-items/{id}/void", { params: { path: { id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["pay-items"] }),
  });
  const labels = useGridLabels(t("designS7.payroll.noItems"));
  const phone = useIsPhone();
  const release = (item: PayItem) =>
    canManage && item.status === "held" ? (
      <Button
        size="sm"
        variant={phone ? "secondary" : "ghost"}
        onClick={() => act.mutate({ id: item.id, kind: "release" })}
      >
        {t("payroll.release")}
      </Button>
    ) : null;
  const columns = useMemo<ColumnDef<PayItem, unknown>[]>(
    () => [
      {
        id: "date",
        header: t("payroll.date"),
        cell: ({ row }) => (
          <span className="whitespace-nowrap">{formatDate(row.original.date, i18n.language)}</span>
        ),
      },
      { id: "tutor", header: t("payroll.tutor"), cell: ({ row }) => row.original.tutor_name },
      {
        id: "description",
        header: t("payroll.description"),
        cell: ({ row }) => {
          const reasons = (row.original.hold_reasons as string[]).map((r) =>
            t(`pay.holdReasons.${r}`),
          );
          return (
            <>
              {withoutIsoDate(row.original.description, row.original.date)}
              {/* On phones the tutor and date fold into one caption under the description. */}
              {phone ? (
                <span className="block text-xs text-muted-foreground tabular-nums">
                  {row.original.tutor_name} · {formatDate(row.original.date, i18n.language)}
                </span>
              ) : null}
              {reasons.length ? (
                <span className="block text-xs text-muted-foreground">{reasons.join(" · ")}</span>
              ) : null}
              {phone ? <div className="mt-1.5">{release(row.original)}</div> : null}
            </>
          );
        },
      },
      {
        id: "amount",
        header: () => <EndHead>{t("payroll.amount")}</EndHead>,
        cell: ({ row }) => <Figure>{formatMoney(row.original.amount)}</Figure>,
      },
      {
        id: "actions",
        // `relative` keeps the visually hidden heading inside the table's scroll box.
        header: () => (
          <span className="relative">
            <span className="sr-only">{t("payroll.actions")}</span>
          </span>
        ),
        cell: ({ row }) => release(row.original),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- labels follow the language
    [t, i18n.language, canManage, phone],
  );
  return (
    <Page title={t("payroll.items")}>
      <div>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <SelectField
            size="sm"
            hideLabel
            label={t("payroll.status")}
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            options={["held", "ready", "in_pay_run", "approved", "paid"].map((s) => ({
              value: s,
              label: t(`payroll.itemStatus.${s}`),
            }))}
          />
        </div>
        <DataGrid
          // On phones the date and tutor fold into the description.
          key={phone ? "phone" : "wide"}
          initialColumnVisibility={
            phone ? { date: false, tutor: false, actions: false } : undefined
          }
          caption={t("payroll.items")}
          rows={items.data?.results ?? []}
          columns={columns}
          getRowId={(r) => r.id}
          isLoading={items.isPending}
          labels={labels}
        />
        {act.error ? (
          <Alert tone="danger" className="mt-4">
            {act.error.message}
          </Alert>
        ) : null}
      </div>
    </Page>
  );
}
