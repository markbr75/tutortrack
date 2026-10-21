import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  PanelFooter,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, usePermission } from "../api";
import { RecordSyncBadge } from "../accounting/SyncBadge";
import { ErrorList } from "../calendar/ErrorList";
import { InvoiceStatus, rowClass } from "./moneyUi";

type Invoice = components["schemas"]["InvoiceDetail"];
type Mode = "view" | "void" | "write_off" | "credit" | "add_line";

/** An invoice's state in words (kept under its old name for the billing lists). */
export const StatusBadge = InvoiceStatus;

/** One invoice: lines, totals and every action its state allows (FR-10-4/5). */
export function InvoicePage({ invoiceId }: { invoiceId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canCreate = usePermission("billing.invoice.create");
  const canIssue = usePermission("billing.invoice.issue");
  const canVoid = usePermission("billing.invoice.void");
  const canWriteOff = usePermission("billing.invoice.write_off");
  const canCredit = usePermission("billing.credit_note.issue");
  const canCollect = usePermission("payments.payment.record");
  const [mode, setMode] = useState<Mode>("view");
  const [reason, setReason] = useState("");
  const [application, setApplication] = useState<"invoice" | "credit">("invoice");
  const [credits, setCredits] = useState<Record<string, string>>({});
  const [line, setLine] = useState({ description: "", amount: "" });
  const key = ["invoice", invoiceId];
  const invoice = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/invoices/{id}", { params: { path: { id: invoiceId } } })),
  });

  const act = useMutation({
    mutationFn: async (
      kind: Mode | "issue" | "send" | "apply" | "remove" | "delete" | "collect",
    ) => {
      const path = { params: { path: { id: invoiceId } } };
      const inv = invoice.data!;
      switch (kind) {
        case "issue":
          return unwrap(await api.POST("/api/v1/invoices/{id}/issue", path));
        case "send":
          return unwrap(await api.POST("/api/v1/invoices/{id}/send", path));
        case "void":
          return unwrap(
            await api.POST("/api/v1/invoices/{id}/void", { ...path, body: { reason } }),
          );
        case "write_off":
          return unwrap(
            await api.POST("/api/v1/invoices/{id}/write-off", { ...path, body: { reason } }),
          );
        case "credit": {
          const lines = Object.entries(credits)
            .filter(([, amount]) => Number(amount) > 0)
            .map(([id, amount]) => ({ line: id, amount }));
          await api
            .POST("/api/v1/invoices/{id}/credit-note", {
              ...path,
              body: { reason, application, lines: lines.length ? lines : undefined },
            })
            .then(unwrap);
          return null;
        }
        case "apply":
          await api.POST("/api/v1/invoices/{id}/apply-credit", { ...path, body: {} }).then(unwrap);
          return null;
        case "add_line":
          return unwrap(
            await api.POST("/api/v1/invoices/{id}/add-line", {
              ...path,
              body: {
                description: line.description,
                unit_price: { amount: line.amount, currency: inv.currency },
                quantity: "1",
              },
            }),
          );
        case "delete":
          await api.DELETE("/api/v1/invoices/{id}", path);
          return null;
        case "collect":
          await api
            .POST("/api/v1/invoices/{invoice_id}/collect", {
              params: { path: { invoice_id: invoiceId } },
            })
            .then(unwrap);
          return null;
        default:
          return null;
      }
    },
    onSuccess: (data, kind) => {
      setMode("view");
      setReason("");
      setCredits({});
      setLine({ description: "", amount: "" });
      if (data) queryClient.setQueryData(key, data);
      void queryClient.invalidateQueries({ queryKey: kind === "delete" ? ["invoices"] : key });
      void queryClient.invalidateQueries({ queryKey: ["invoices"] });
    },
  });
  const removeLine = useMutation({
    mutationFn: async (lineId: string) =>
      unwrap(
        await api.POST("/api/v1/invoices/{id}/remove-line", {
          params: { path: { id: invoiceId } },
          body: { line: lineId },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(key, data),
  });

  if (invoice.isPending) return <Spinner label={t("grid.loading")} />;
  if (!invoice.data) return <ErrorList error={invoice.error} />;
  const inv: Invoice = invoice.data;
  const money = (value: { amount: string; currency: string }) => formatMoney(value, i18n.language);
  const draft = inv.status === "draft";
  const open = inv.status === "issued" || inv.status === "partially_paid";
  const issued = !draft && inv.status !== "void";
  const crediting = mode === "credit";
  const removing = draft && canCreate;
  // Columns after the amount, so the totals stay in the amount column.
  const trailing = (crediting ? 1 : 0) + (removing ? 1 : 0);
  const amountPad = trailing ? "pr-4" : "pr-5";
  const totals: { key: string; label: string; value: string; due?: boolean }[] = [
    ...(Number(inv.tax_total.amount)
      ? [
          { key: "subtotal", label: t("billing.subtotal"), value: money(inv.subtotal) },
          { key: "tax", label: t("billing.tax"), value: money(inv.tax_total) },
        ]
      : []),
    { key: "total", label: t("billing.total"), value: money(inv.total) },
    ...(Number(inv.amount_credited.amount)
      ? [
          {
            key: "credited",
            label: t("billing.creditApplied"),
            value: `−${money(inv.amount_credited)}`,
          },
        ]
      : []),
    ...(Number(inv.amount_paid.amount)
      ? [{ key: "paid", label: t("billing.paid"), value: `−${money(inv.amount_paid)}` }]
      : []),
    { key: "due", label: t("billing.balanceDue"), value: money(inv.balance_due), due: true },
  ];
  const context = [
    inv.issue_date ? `${t("billing.issued")} ${formatDate(inv.issue_date, i18n.language)}` : "",
    inv.due_date ? `${t("billing.due")} ${formatDate(inv.due_date, i18n.language)}` : "",
  ].filter(Boolean);

  return (
    <article className="space-y-6">
      <p className="text-sm">
        <Link to="/billing" className="font-medium text-link hover:underline">
          {t("billing.title")}
        </Link>
      </p>
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">
            <span className="tabular-nums">{inv.number || t("billing.draftInvoice")}</span>
            {/* "Draft invoice" already says it; the status word follows a number only. */}
            {inv.number ? (
              <>
                {" "}
                <InvoiceStatus
                  status={inv.status}
                  overdue={inv.is_overdue}
                  className="ml-2 align-middle text-base font-medium"
                />
              </>
            ) : null}
          </h1>
          <p className="mt-1 text-muted-foreground">
            <Link
              to="/clients/$clientId"
              params={{ clientId: inv.client }}
              className="text-foreground underline-offset-2 hover:underline"
            >
              {inv.client_name}
            </Link>
            {context.length ? <span className="tabular-nums"> · {context.join(" · ")}</span> : null}
            {inv.status !== "draft" ? (
              <span className="ml-2 text-sm">
                <RecordSyncBadge objectType="invoice" id={inv.id} />
              </span>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {open && canVoid ? (
            <Button size="sm" variant="ghost" onClick={() => setMode("void")}>
              {t("billing.void")}
            </Button>
          ) : null}
          {open && canWriteOff ? (
            <Button size="sm" variant="ghost" onClick={() => setMode("write_off")}>
              {t("billing.writeOff")}
            </Button>
          ) : null}
          {draft && canCreate ? (
            <Button size="sm" variant="ghost" onClick={() => act.mutate("delete")}>
              {t("billing.deleteDraft")}
            </Button>
          ) : null}
          <a
            className={buttonClass({ variant: "secondary", size: "sm" })}
            href={`/api/v1/invoices/${inv.id}/pdf`}
            target="_blank"
            rel="noreferrer"
          >
            {t("billing.pdf")}
          </a>
          {issued && canIssue ? (
            <Button size="sm" variant="secondary" onClick={() => act.mutate("send")}>
              {t("billing.send")}
            </Button>
          ) : null}
          {open && canCredit ? (
            <>
              <Button size="sm" variant="secondary" onClick={() => setMode("credit")}>
                {t("billing.creditNote")}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => act.mutate("apply")}>
                {t("billing.applyCredit")}
              </Button>
            </>
          ) : null}
          {open && canCollect ? (
            <Button size="sm" variant="secondary" onClick={() => act.mutate("collect")}>
              {t("payments.collectNow")}
            </Button>
          ) : null}
          {draft && canIssue ? (
            <Button onClick={() => act.mutate("issue")} disabled={act.isPending}>
              {t("billing.issue")}
            </Button>
          ) : null}
        </div>
      </header>
      {act.isSuccess && !act.data && mode === "view" ? (
        <Alert tone="success">{t("billing.done")}</Alert>
      ) : null}
      <ErrorList error={act.error ?? removeLine.error} />

      <div
        className={
          inv.credit_notes.length
            ? "grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]"
            : "max-w-5xl"
        }
      >
        <div className="min-w-0 space-y-6">
          {mode === "void" || mode === "write_off" ? (
            <RuledPanel
              flush
              title={mode === "void" ? t("billing.confirmVoid") : t("billing.confirmWriteOff")}
            >
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  act.mutate(mode);
                }}
              >
                <div className="max-w-md px-5 py-4">
                  <TextField
                    label={t("billing.reason")}
                    value={reason}
                    required
                    onChange={(e) => setReason(e.target.value)}
                  />
                </div>
                <PanelFooter>
                  <Button type="submit" variant="danger">
                    {mode === "void" ? t("billing.confirmVoid") : t("billing.confirmWriteOff")}
                  </Button>
                  <Button variant="ghost" onClick={() => setMode("view")}>
                    {t("common.cancel")}
                  </Button>
                </PanelFooter>
              </form>
            </RuledPanel>
          ) : null}

          <section
            aria-labelledby="invoice-lines-h"
            className="rounded-xl border border-border bg-surface"
          >
            <div className="flex items-baseline justify-between gap-3 border-b border-border px-5 py-3.5">
              <h2 id="invoice-lines-h" className="text-base font-semibold">
                {t("billing.lines")}
              </h2>
              <span className="text-sm text-muted-foreground">{inv.currency}</span>
            </div>
            <div
              role="region"
              aria-labelledby="invoice-lines-h"
              tabIndex={0}
              className="overflow-x-auto"
            >
              <table className="w-full min-w-[36rem] text-left text-sm">
                <caption className="sr-only">{t("billing.lines")}</caption>
                <thead className="border-b border-border">
                  <tr>
                    <th scope="col" className="w-28 py-2.5 pr-4 pl-5">
                      {t("billing.date")}
                    </th>
                    <th scope="col" className="px-4 py-2.5">
                      {t("billing.description")}
                    </th>
                    <th scope="col" className="px-4 py-2.5">
                      {t("billing.student")}
                    </th>
                    <th scope="col" className={`w-32 py-2.5 pl-4 text-right ${amountPad}`}>
                      {t("billing.amount")}
                    </th>
                    {crediting ? (
                      <th scope="col" className="w-36 px-4 py-2.5 text-right">
                        {t("billing.creditAmount")}
                      </th>
                    ) : null}
                    {removing ? (
                      <th scope="col" className="w-28 py-2.5 pr-5 pl-4">
                        <span className="sr-only">{t("billing.remove")}</span>
                      </th>
                    ) : null}
                  </tr>
                </thead>
                <tbody>
                  {inv.lines.map((row) => (
                    <tr key={row.id}>
                      <td className="py-2.5 pr-4 pl-5 align-top whitespace-nowrap">
                        {formatDate(row.date, i18n.language)}
                      </td>
                      <td className="px-4 py-2.5 align-top">
                        {row.description}
                        {row.tutor_name ? (
                          <span className="block text-xs text-muted-foreground">
                            {row.tutor_name}
                          </span>
                        ) : null}
                      </td>
                      <td className="px-4 py-2.5 align-top">{row.student_name}</td>
                      <td className={`py-2.5 pl-4 text-right align-top ${amountPad}`}>
                        {money(row.gross)}
                        {Number(row.credited.amount) ? (
                          <span className="block text-xs text-muted-foreground">
                            {t("billing.credited", { amount: money(row.credited) })}
                          </span>
                        ) : null}
                      </td>
                      {crediting && row.kind === "discount" ? (
                        <td className="px-4 py-2.5 text-right align-top text-xs text-muted-foreground">
                          {t("g3.billing.creditedWithLine")}
                        </td>
                      ) : crediting ? (
                        <td className="px-4 py-1.5 align-top">
                          <TextField
                            className="ml-auto w-28 text-right"
                            type="number"
                            min={0}
                            step="0.01"
                            hideLabel
                            label={t("billing.creditFor", { description: row.description })}
                            value={credits[row.id] ?? ""}
                            onChange={(e) =>
                              setCredits((c) => ({ ...c, [row.id]: e.target.value }))
                            }
                          />
                        </td>
                      ) : null}
                      {removing && row.kind === "discount" ? (
                        <td className="py-2.5 pr-5 pl-4 text-right align-top text-xs text-muted-foreground">
                          {t("g3.billing.removedWithLine")}
                        </td>
                      ) : removing ? (
                        <td className="py-1.5 pr-5 pl-4 text-right align-top">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => removeLine.mutate(row.id)}
                          >
                            {t("billing.remove")}
                            <span className="sr-only"> {row.description}</span>
                          </Button>
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  {totals.map((row, i) => (
                    <tr
                      key={row.key}
                      className={i === 0 || row.due ? "border-t border-border" : ""}
                    >
                      <th
                        scope="row"
                        colSpan={3}
                        className={
                          row.due
                            ? "py-3 pr-4 pl-5 text-right text-base font-semibold"
                            : "py-2 pr-4 pl-5 text-right text-sm font-normal text-muted-foreground"
                        }
                      >
                        {row.label}
                      </th>
                      <td
                        className={`pl-4 text-right ${amountPad} ${row.due ? "py-3 text-base font-semibold" : "py-2"}`}
                      >
                        {row.value}
                      </td>
                      {trailing ? <td colSpan={trailing} /> : null}
                    </tr>
                  ))}
                </tfoot>
              </table>
            </div>

            {crediting ? (
              <form
                className="space-y-3 border-t border-border px-5 py-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  act.mutate("credit");
                }}
              >
                <p className="text-sm text-muted-foreground">{t("billing.creditHelp")}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <TextField
                    label={t("billing.reason")}
                    value={reason}
                    required
                    onChange={(e) => setReason(e.target.value)}
                  />
                  <SelectField
                    label={t("billing.creditUse")}
                    value={application}
                    onChange={(e) => setApplication(e.target.value as "invoice" | "credit")}
                    options={[
                      { value: "invoice", label: t("billing.creditToInvoice") },
                      { value: "credit", label: t("billing.creditToClient") },
                    ]}
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="submit">{t("billing.issueCreditNote")}</Button>
                  <Button variant="ghost" onClick={() => setMode("view")}>
                    {t("common.cancel")}
                  </Button>
                </div>
              </form>
            ) : null}

            {draft && canCreate ? (
              <form
                className="flex flex-wrap items-end gap-2 border-t border-rule px-5 py-3"
                aria-label={t("billing.addLine")}
                onSubmit={(e) => {
                  e.preventDefault();
                  act.mutate("add_line");
                }}
              >
                <div className="min-w-56 flex-1">
                  <TextField
                    label={t("billing.description")}
                    value={line.description}
                    required
                    onChange={(e) => setLine((l) => ({ ...l, description: e.target.value }))}
                  />
                </div>
                <div className="w-36">
                  <TextField
                    label={t("billing.amount")}
                    type="number"
                    step="0.01"
                    value={line.amount}
                    required
                    onChange={(e) => setLine((l) => ({ ...l, amount: e.target.value }))}
                  />
                </div>
                <Button type="submit" variant="secondary">
                  {t("billing.addLine")}
                </Button>
              </form>
            ) : null}
          </section>
        </div>

        {inv.credit_notes.length ? (
          <RuledPanel flush titleId="credit-notes-title" title={t("billing.creditNotes")}>
            <ul>
              {inv.credit_notes.map((note) => (
                <li key={note.id} className={rowClass}>
                  <div className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="font-medium tabular-nums">{note.number}</span>
                    <span className="font-semibold tabular-nums">{money(note.total)}</span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {note.reason}
                    {note.reason ? " · " : ""}
                    <a
                      className="text-link underline-offset-2 hover:underline"
                      href={`/api/v1/credit-notes/${note.id}/pdf`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t("g3.billing.creditNotePdf", { number: note.number })}
                    </a>
                  </p>
                </li>
              ))}
            </ul>
          </RuledPanel>
        ) : null}
      </div>
    </article>
  );
}
