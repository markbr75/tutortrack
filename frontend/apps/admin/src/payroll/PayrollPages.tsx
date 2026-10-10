import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";

import { api, usePermission } from "../api";

type Totals = Record<string, string>;

function totals(values: Totals | undefined): string {
  const entries = Object.entries(values ?? {});
  return entries.length
    ? entries.map(([currency, amount]) => formatMoney({ amount, currency })).join(" + ")
    : "–";
}

function PayrollNav() {
  const { t } = useTranslation();
  const links = [
    { to: "/payroll", label: t("payroll.runs") },
    { to: "/payroll/expenses", label: t("payroll.expenses") },
    { to: "/payroll/items", label: t("payroll.items") },
  ] as const;
  return (
    <nav aria-label={t("payroll.title")} className="mb-4 flex gap-3 text-sm">
      {links.map((l) => (
        <Link
          key={l.to}
          to={l.to}
          activeOptions={{ exact: true }}
          className="rounded-md px-2 py-1 hover:bg-muted [&.active]:font-medium"
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}

function Page({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="max-w-5xl space-y-4">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <PayrollNav />
      {children}
    </div>
  );
}

/** Pay runs (FR-12-5): list and open a new one for a period. */
export function PayRunsPage() {
  const { t } = useTranslation();
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
  return (
    <Page title={t("payroll.title")}>
      {canCreate ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <TextField
            label={t("payroll.periodStart")}
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
          <TextField
            label={t("payroll.periodEnd")}
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
          <Button type="submit" loading={create.isPending}>
            {t("payroll.newRun")}
          </Button>
        </form>
      ) : null}
      {create.error ? <Alert tone="danger">{create.error.message}</Alert> : null}
      {runs.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th scope="col">{t("payroll.number")}</th>
              <th scope="col">{t("payroll.period")}</th>
              <th scope="col">{t("payroll.status")}</th>
              <th scope="col">{t("payroll.total")}</th>
            </tr>
          </thead>
          <tbody>
            {runs.data?.results.map((run) => (
              <tr key={run.id} className="border-t border-border">
                <td>
                  <Link to="/payroll/runs/$id" params={{ id: run.id }} className="underline">
                    {run.number}
                  </Link>
                </td>
                <td>
                  {formatDate(run.period_start)} – {formatDate(run.period_end)}
                </td>
                <td>{t(`payroll.runStatus.${run.status}`)}</td>
                <td>{totals(run.totals as Totals)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}

type PayRun = components["schemas"]["PayRunDetail"];

/** Review, approve, pay and download (FR-12-5..8). */
export function PayRunPage({ id }: { id: string }) {
  const { t } = useTranslation();
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
  if (!run.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const r = run.data;
  const paying = r.status === "approved" || r.status === "paying";
  const error = approve.error ?? cancel.error ?? markPaid.error ?? bankFile.error;
  return (
    <Page title={`${t("payroll.run")} ${r.number}`}>
      <p className="text-sm">
        {formatDate(r.period_start)} – {formatDate(r.period_end)} ·{" "}
        {t(`payroll.runStatus.${r.status}`)} · {totals(r.totals as Totals)}
      </p>
      {(r.warnings as { code: string; message: string }[]).map((w, i) => (
        <Alert key={i} tone="warning">
          {w.message}
        </Alert>
      ))}
      {r.approvals_required > 1 ? (
        <p className="text-sm">
          {t("payroll.approvals", {
            count: (r.approvals as unknown[]).length,
            required: r.approvals_required,
          })}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {r.status === "review" && canApprove ? (
          <Button onClick={() => approve.mutate()} loading={approve.isPending}>
            {t("payroll.approve")}
          </Button>
        ) : null}
        {["review", "approved"].includes(r.status) ? (
          <Button variant="ghost" onClick={() => cancel.mutate()}>
            {t("payroll.cancelRun")}
          </Button>
        ) : null}
        {paying && canPay ? (
          <>
            <label className="flex items-center gap-2 text-sm">
              <span>{t("payroll.fileFormat")}</span>
              <select
                className="h-9 rounded-md border border-border bg-background px-2"
                value={format}
                onChange={(e) => setFormat(e.target.value)}
              >
                <option value="">{t("payroll.defaultFormat")}</option>
                {["csv", "bacs18", "sepa", "nacha", "aba"].map((f) => (
                  <option key={f} value={f}>
                    {f.toUpperCase()}
                  </option>
                ))}
              </select>
            </label>
            <Button variant="secondary" onClick={() => bankFile.mutate()}>
              {t("payroll.makeBankFile")}
            </Button>
            <Button variant="secondary" onClick={() => markPaid.mutate()}>
              {t("payroll.markPaid")}
            </Button>
          </>
        ) : null}
      </div>
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
      {r.bank_files.length ? (
        <ul className="text-sm">
          {r.bank_files.map((f) => (
            <li key={f.id}>
              <a className="underline" href={`/api/v1/pay-runs/${id}/bank-files/${f.id}`}>
                {f.filename}
              </a>{" "}
              ({f.payout_count})
            </li>
          ))}
        </ul>
      ) : null}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th scope="col">{t("payroll.tutor")}</th>
              <th scope="col">{t("payroll.method")}</th>
              <th scope="col">{t("payroll.status")}</th>
              <th scope="col">{t("payroll.amount")}</th>
              <th scope="col">{t("payroll.statement")}</th>
            </tr>
          </thead>
          <tbody>
            {r.payouts.map((p) => (
              <tr key={p.id} className="border-t border-border">
                <td>{p.tutor_name}</td>
                <td>{t(`payroll.methods.${p.method}`)}</td>
                <td>
                  {t(`payroll.payoutStatus.${p.status}`)}
                  {p.failure_reason ? ` · ${p.failure_reason}` : ""}
                </td>
                <td>{formatMoney(p.amount)}</td>
                <td>
                  {p.statement ? (
                    <a className="underline" href={`/api/v1/pay-statements/${p.statement.id}/pdf`}>
                      {p.statement.number}
                    </a>
                  ) : (
                    "–"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-sm">
        {t("payroll.exportFor")}{" "}
        {["xero", "quickbooks", "brightpay", "gusto", "generic"].map((f) => (
          <a
            key={f}
            className="mr-2 underline"
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
  const { t } = useTranslation();
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
  return (
    <Page title={t("payroll.expenses")}>
      {claims.data && !claims.data.results.length ? (
        <p className="text-sm">{t("payroll.noClaims")}</p>
      ) : null}
      <ul className="space-y-3">
        {claims.data?.results.map((claim) => (
          <li key={claim.id} className="space-y-2 rounded-md border border-border p-3 text-sm">
            <p>
              <strong>{claim.tutor_name}</strong> · {claim.category_name} · {formatDate(claim.date)}{" "}
              · {formatMoney(claim.amount)}
              {claim.rebillable ? ` · ${t("payroll.rebillable")}` : ""}
            </p>
            <p>{claim.description}</p>
            {claim.receipt ? (
              <a className="underline" href={`/api/v1/files/${claim.receipt}/download`}>
                {t("payroll.receipt")}
              </a>
            ) : null}
            <div className="flex flex-wrap items-end gap-2">
              <TextField
                label={t("payroll.comment")}
                value={comment[claim.id] ?? ""}
                onChange={(e) => setComment({ ...comment, [claim.id]: e.target.value })}
              />
              <Button size="sm" onClick={() => decide.mutate({ id: claim.id, verdict: "approve" })}>
                {t("payroll.approveClaim")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => decide.mutate({ id: claim.id, verdict: "reject" })}
              >
                {t("payroll.rejectClaim")}
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {decide.error ? <Alert tone="danger">{decide.error.message}</Alert> : null}
    </Page>
  );
}

/** All pay items, with holds (FR-12-1). */
export function PayItemsPage() {
  const { t } = useTranslation();
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
  return (
    <Page title={t("payroll.items")}>
      <label className="flex items-center gap-2 text-sm">
        <span>{t("payroll.status")}</span>
        <select
          className="h-9 rounded-md border border-border bg-background px-2"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          {["held", "ready", "in_pay_run", "approved", "paid"].map((s) => (
            <option key={s} value={s}>
              {t(`payroll.itemStatus.${s}`)}
            </option>
          ))}
        </select>
      </label>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th scope="col">{t("payroll.date")}</th>
              <th scope="col">{t("payroll.tutor")}</th>
              <th scope="col">{t("payroll.description")}</th>
              <th scope="col">{t("payroll.amount")}</th>
              <th scope="col">
                <span className="sr-only">{t("payroll.actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.data?.results.map((item) => (
              <tr key={item.id} className="border-t border-border align-top">
                <td>{formatDate(item.date)}</td>
                <td>{item.tutor_name}</td>
                <td>
                  {item.description}
                  {(item.hold_reasons as string[]).map((r) => (
                    <div key={r} className="text-xs text-muted-foreground">
                      {t(`pay.holdReasons.${r}`)}
                    </div>
                  ))}
                </td>
                <td>{formatMoney(item.amount)}</td>
                <td>
                  {canManage && item.status === "held" ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => act.mutate({ id: item.id, kind: "release" })}
                    >
                      {t("payroll.release")}
                    </Button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}
