import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";

type Invoice = components["schemas"]["InvoiceDetail"];
type Mode = "view" | "void" | "write_off" | "credit" | "add_line";

export function StatusBadge({ status, overdue }: { status: string; overdue?: boolean }) {
  const { t } = useTranslation();
  const tone =
    status === "paid"
      ? "bg-success/15"
      : overdue
        ? "bg-danger/15 text-danger"
        : status === "draft"
          ? "bg-muted"
          : "bg-amber-500/15";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${tone}`}>
      {overdue ? t("billing.status.overdue") : t(`billing.status.${status}`)}
    </span>
  );
}

/** One invoice: lines, totals and every action its state allows (FR-10-4/5). */
export function InvoicePage({ invoiceId }: { invoiceId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canCreate = usePermission("billing.invoice.create");
  const canIssue = usePermission("billing.invoice.issue");
  const canVoid = usePermission("billing.invoice.void");
  const canWriteOff = usePermission("billing.invoice.write_off");
  const canCredit = usePermission("billing.credit_note.issue");
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
    mutationFn: async (kind: Mode | "issue" | "send" | "apply" | "remove" | "delete") => {
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

  if (invoice.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  if (!invoice.data) return <ErrorList error={invoice.error} />;
  const inv: Invoice = invoice.data;
  const money = (value: { amount: string; currency: string }) => formatMoney(value, i18n.language);
  const draft = inv.status === "draft";
  const open = inv.status === "issued" || inv.status === "partially_paid";
  const issued = !draft && inv.status !== "void";

  return (
    <article className="max-w-4xl space-y-6">
      <p className="text-sm">
        <Link to="/billing" className="font-medium underline-offset-2 hover:underline">
          {t("billing.title")}
        </Link>
      </p>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">
            {inv.number || t("billing.draftInvoice")}{" "}
            <StatusBadge status={inv.status} overdue={inv.is_overdue} />
          </h1>
          <p className="text-sm text-muted-foreground">
            <Link
              to="/clients/$clientId"
              params={{ clientId: inv.client }}
              className="underline-offset-2 hover:underline"
            >
              {inv.client_name}
            </Link>
            {inv.issue_date
              ? ` · ${t("billing.issued")} ${formatDate(inv.issue_date, i18n.language)}`
              : ""}
            {inv.due_date
              ? ` · ${t("billing.due")} ${formatDate(inv.due_date, i18n.language)}`
              : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            className="rounded-md border border-border px-3 py-1.5 text-sm"
            href={`/api/v1/invoices/${inv.id}/pdf`}
            target="_blank"
            rel="noreferrer"
          >
            {t("billing.pdf")}
          </a>
          {draft && canIssue ? (
            <Button size="sm" onClick={() => act.mutate("issue")} disabled={act.isPending}>
              {t("billing.issue")}
            </Button>
          ) : null}
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
        </div>
      </header>
      {act.isSuccess && !act.data && mode === "view" ? (
        <Alert tone="success">{t("billing.done")}</Alert>
      ) : null}
      <ErrorList error={act.error ?? removeLine.error} />

      {mode === "void" || mode === "write_off" ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            act.mutate(mode);
          }}
        >
          <TextField
            label={t("billing.reason")}
            value={reason}
            required
            onChange={(e) => setReason(e.target.value)}
          />
          <Button type="submit" variant="danger">
            {mode === "void" ? t("billing.confirmVoid") : t("billing.confirmWriteOff")}
          </Button>
        </form>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{t("billing.lines")}</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="py-2 pr-3">
                {t("billing.date")}
              </th>
              <th scope="col" className="py-2 pr-3">
                {t("billing.description")}
              </th>
              <th scope="col" className="py-2 pr-3">
                {t("billing.student")}
              </th>
              <th scope="col" className="py-2 pr-3 text-right">
                {t("billing.amount")}
              </th>
              {mode === "credit" ? (
                <th scope="col" className="py-2 pr-3 text-right">
                  {t("billing.creditAmount")}
                </th>
              ) : null}
              {draft && canCreate ? (
                <th scope="col">
                  <span className="sr-only">{t("billing.remove")}</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {inv.lines.map((row) => (
              <tr key={row.id} className="border-b border-border">
                <td className="py-2 pr-3">{formatDate(row.date, i18n.language)}</td>
                <td className="py-2 pr-3">
                  {row.description}
                  {row.tutor_name ? (
                    <span className="block text-muted-foreground">{row.tutor_name}</span>
                  ) : null}
                </td>
                <td className="py-2 pr-3">{row.student_name}</td>
                <td className="py-2 pr-3 text-right">
                  {money(row.gross)}
                  {Number(row.credited.amount) ? (
                    <span className="block text-xs text-muted-foreground">
                      {t("billing.credited", { amount: money(row.credited) })}
                    </span>
                  ) : null}
                </td>
                {mode === "credit" ? (
                  <td className="py-2 pr-3 text-right">
                    <TextField
                      className="w-28"
                      type="number"
                      min={0}
                      step="0.01"
                      label={t("billing.creditFor", { description: row.description })}
                      value={credits[row.id] ?? ""}
                      onChange={(e) => setCredits((c) => ({ ...c, [row.id]: e.target.value }))}
                    />
                  </td>
                ) : null}
                {draft && canCreate ? (
                  <td className="py-2 text-right">
                    <Button size="sm" variant="ghost" onClick={() => removeLine.mutate(row.id)}>
                      {t("billing.remove")}
                      <span className="sr-only"> {row.description}</span>
                    </Button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {mode === "credit" ? (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            act.mutate("credit");
          }}
        >
          <p className="text-sm text-muted-foreground">{t("billing.creditHelp")}</p>
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
          <Button type="submit">{t("billing.issueCreditNote")}</Button>
        </form>
      ) : null}

      {draft && canCreate ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            act.mutate("add_line");
          }}
        >
          <TextField
            label={t("billing.description")}
            value={line.description}
            required
            onChange={(e) => setLine((l) => ({ ...l, description: e.target.value }))}
          />
          <TextField
            label={t("billing.amount")}
            type="number"
            step="0.01"
            value={line.amount}
            required
            onChange={(e) => setLine((l) => ({ ...l, amount: e.target.value }))}
          />
          <Button type="submit" variant="secondary">
            {t("billing.addLine")}
          </Button>
        </form>
      ) : null}

      <dl className="ml-auto grid max-w-xs grid-cols-2 gap-1 text-sm">
        {Number(inv.tax_total.amount) ? (
          <>
            <dt>{t("billing.subtotal")}</dt>
            <dd className="text-right">{money(inv.subtotal)}</dd>
            <dt>{t("billing.tax")}</dt>
            <dd className="text-right">{money(inv.tax_total)}</dd>
          </>
        ) : null}
        <dt>{t("billing.total")}</dt>
        <dd className="text-right">{money(inv.total)}</dd>
        {Number(inv.amount_credited.amount) ? (
          <>
            <dt>{t("billing.creditApplied")}</dt>
            <dd className="text-right">−{money(inv.amount_credited)}</dd>
          </>
        ) : null}
        {Number(inv.amount_paid.amount) ? (
          <>
            <dt>{t("billing.paid")}</dt>
            <dd className="text-right">−{money(inv.amount_paid)}</dd>
          </>
        ) : null}
        <dt className="font-semibold">{t("billing.balanceDue")}</dt>
        <dd className="text-right font-semibold">{money(inv.balance_due)}</dd>
      </dl>

      {inv.credit_notes.length ? (
        <section aria-labelledby="credit-notes-title">
          <h2 id="credit-notes-title" className="text-lg font-semibold">
            {t("billing.creditNotes")}
          </h2>
          <ul className="mt-2 space-y-1 text-sm">
            {inv.credit_notes.map((note) => (
              <li key={note.id}>
                {note.number} · {money(note.total)} · {note.reason}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
}
