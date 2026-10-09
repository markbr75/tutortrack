import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { toDateInput } from "../calendar/dates";

type Method = components["schemas"]["RecordPaymentRequest"]["method"];
const METHODS: Method[] = ["bank_transfer", "cash", "cheque", "direct_debit", "other"];

/** Record a bank transfer, cash, cheque or other payment (FR-11-5) and choose which
 * invoices it pays (oldest first by default, FR-11-6). */
export function RecordPayment({
  clientId,
  currency,
  onDone,
}: {
  clientId: string;
  currency: string;
  onDone?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    amount: "",
    method: "bank_transfer" as Method,
    date: toDateInput(new Date()),
    reference: "",
  });
  const [split, setSplit] = useState<Record<string, string> | null>(null);
  const open = useQuery({
    queryKey: ["invoices", "client", clientId, "open"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/invoices", {
          params: { query: { client: clientId, status: ["issued", "partially_paid"] } },
        }),
      ),
  });
  const invoices = [...(open.data?.results ?? [])].sort((a, b) =>
    (a.due_date ?? "").localeCompare(b.due_date ?? ""),
  );
  const record = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/payments", {
          body: {
            client: clientId,
            amount: { amount: form.amount, currency },
            method: form.method,
            received_at: new Date(`${form.date}T12:00:00`).toISOString(),
            reference: form.reference,
            notes: "",
            allocations: split
              ? Object.entries(split)
                  .filter(([, amount]) => Number(amount) > 0)
                  .map(([invoice, amount]) => ({ invoice, amount }))
              : undefined,
          },
        }),
      ),
    onSuccess: () => {
      setForm((f) => ({ ...f, amount: "", reference: "" }));
      setSplit(null);
      void queryClient.invalidateQueries({ queryKey: ["invoices"] });
      void queryClient.invalidateQueries({ queryKey: ["client", clientId] });
      void queryClient.invalidateQueries({ queryKey: ["payments"] });
      onDone?.();
    },
  });

  return (
    <form
      className="space-y-3"
      aria-label={t("payments.record")}
      onSubmit={(e) => {
        e.preventDefault();
        record.mutate();
      }}
    >
      <div className="flex flex-wrap items-end gap-2">
        <TextField
          type="number"
          step="0.01"
          min={0}
          required
          label={t("payments.amount")}
          value={form.amount}
          onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
        />
        <SelectField
          label={t("payments.method")}
          value={form.method}
          onChange={(e) => setForm((f) => ({ ...f, method: e.target.value as Method }))}
          options={METHODS.map((m) => ({ value: m, label: t(`payments.methods.${m}`) }))}
        />
        <TextField
          type="date"
          label={t("payments.received")}
          value={form.date}
          onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
        />
        <TextField
          label={t("payments.reference")}
          value={form.reference}
          onChange={(e) => setForm((f) => ({ ...f, reference: e.target.value }))}
        />
      </div>
      {invoices.length ? (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t("payments.allocate")}</legend>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
              checked={split !== null}
              onChange={(e) => setSplit(e.target.checked ? {} : null)}
            />
            {t("payments.chooseInvoices")}
          </label>
          {split ? (
            <ul className="space-y-1">
              {invoices.map((inv) => (
                <li key={inv.id} className="flex flex-wrap items-end gap-2 text-sm">
                  <TextField
                    className="w-28"
                    type="number"
                    step="0.01"
                    min={0}
                    label={t("payments.payInvoice", {
                      number: inv.number,
                      due: formatMoney(inv.balance_due, i18n.language),
                    })}
                    value={split[inv.id] ?? ""}
                    onChange={(e) => setSplit((s) => ({ ...(s ?? {}), [inv.id]: e.target.value }))}
                  />
                  <span className="text-muted-foreground">
                    {inv.due_date ? formatDate(inv.due_date, i18n.language) : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">{t("payments.oldestFirst")}</p>
          )}
        </fieldset>
      ) : null}
      <ErrorList error={record.error} />
      {record.isSuccess ? <Alert tone="success">{t("payments.recorded")}</Alert> : null}
      <Button type="submit" disabled={record.isPending}>
        {t("payments.record")}
      </Button>
    </form>
  );
}

/** Saved payment methods and auto-pay for a client (FR-11-2/3). */
export function ClientPaymentMethods({ clientId }: { clientId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("payments.autopay.manage");
  const key = ["client", clientId, "payment-methods"];
  const methods = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/clients/{client_id}/payment-methods", {
          params: { path: { client_id: clientId } },
        }),
      ),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: key });
  const link = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/clients/{client_id}/payment-methods/setup-link", {
          params: { path: { client_id: clientId } },
        }),
      ),
  });
  const autopay = useMutation({
    mutationFn: async (enabled: boolean) =>
      unwrap(
        await api.POST("/api/v1/clients/{client_id}/autopay", {
          params: { path: { client_id: clientId } },
          body: { enabled },
        }),
      ),
    onSuccess: refresh,
  });
  const change = useMutation({
    mutationFn: async ({ id, kind }: { id: string; kind: "default" | "remove" }) => {
      const path = { params: { path: { id } } };
      if (kind === "default") await api.POST("/api/v1/payment-methods/{id}/default", path);
      else await api.DELETE("/api/v1/payment-methods/{id}", path);
    },
    onSuccess: refresh,
  });
  const data = methods.data;

  return (
    <section aria-labelledby="payment-methods" className="space-y-3">
      <h3 id="payment-methods" className="font-semibold">
        {t("payments.savedMethods")}
      </h3>
      {data?.methods.length ? (
        <ul className="divide-y divide-border rounded-md border border-border text-sm">
          {data.methods.map((m) => (
            <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
              <span>
                {m.type === "card"
                  ? t("payments.card", { brand: m.brand, last4: m.last4 })
                  : t("payments.debit", { last4: m.last4 })}
                {m.exp_month ? ` · ${m.exp_month}/${m.exp_year}` : ""}
                {m.is_default ? ` · ${t("payments.default")}` : ""}
              </span>
              {canManage ? (
                <span className="flex gap-2">
                  {!m.is_default ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => change.mutate({ id: m.id, kind: "default" })}
                    >
                      {t("payments.makeDefault")}
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => change.mutate({ id: m.id, kind: "remove" })}
                  >
                    {t("payments.remove")}
                  </Button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{t("payments.noMethods")}</p>
      )}
      <p className="text-sm">
        {data?.auto_pay
          ? t("payments.autopayOn", {
              date: data.consent_given_at ? formatDate(data.consent_given_at, i18n.language) : "",
            })
          : t("payments.autopayOff")}
      </p>
      {canManage ? (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => link.mutate()}>
            {t("payments.sendSetupLink")}
          </Button>
          {data?.auto_pay ? (
            <Button size="sm" variant="ghost" onClick={() => autopay.mutate(false)}>
              {t("payments.turnOffAutopay")}
            </Button>
          ) : data?.consent_given_at ? (
            <Button size="sm" variant="ghost" onClick={() => autopay.mutate(true)}>
              {t("payments.turnOnAutopay")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {link.data ? (
        <Alert tone="success">
          {t("payments.linkReady")} <code className="break-all text-xs">{link.data.url}</code>
        </Alert>
      ) : null}
      <ErrorList error={link.error ?? autopay.error ?? change.error} />
    </section>
  );
}
