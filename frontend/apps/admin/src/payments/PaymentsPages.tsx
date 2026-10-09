import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import { useCursorList } from "../lists";

type Payment = components["schemas"]["Payment"];

/** Settings → Payments: connect the organisation's own Stripe account (FR-11-1). */
export function PaymentsSettingsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("payments.provider.manage");
  const providers = useQuery({
    queryKey: ["payment-providers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/payments/providers")),
  });
  const connect = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/payments/providers/stripe/connect", { body: { email: "" } })),
    onSuccess: (result) => window.location.assign(result.url),
  });
  const act = useMutation({
    mutationFn: async ({ id, kind }: { id: string; kind: "refresh" | "disconnect" }) => {
      const path = { params: { path: { id } } };
      return kind === "refresh"
        ? unwrap(await api.POST("/api/v1/payments/providers/{id}/refresh", path))
        : unwrap(await api.POST("/api/v1/payments/providers/{id}/disconnect", path));
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["payment-providers"] }),
  });
  const stripe = providers.data?.find((p) => p.provider === "stripe" && !p.branch);

  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-2xl font-semibold">{t("payments.settingsTitle")}</h1>
      <p className="text-sm text-muted-foreground">{t("payments.settingsHelp")}</p>
      {providers.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : stripe ? (
        <section className="space-y-2 rounded-md border border-border p-4">
          <h2 className="font-semibold">Stripe</h2>
          <p className="text-sm">
            {t(`payments.accountStatus.${stripe.status}`)} · {stripe.account_ref}
          </p>
          {stripe.requirements.length ? (
            <Alert tone="warning">{t("payments.requirements")}</Alert>
          ) : null}
          {canManage ? (
            <div className="flex flex-wrap gap-2">
              {stripe.status !== "active" ? (
                <Button size="sm" onClick={() => connect.mutate()}>
                  {t("payments.finishSetup")}
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="secondary"
                onClick={() => act.mutate({ id: stripe.id, kind: "refresh" })}
              >
                {t("payments.checkStatus")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => act.mutate({ id: stripe.id, kind: "disconnect" })}
              >
                {t("payments.disconnect")}
              </Button>
            </div>
          ) : null}
        </section>
      ) : canManage ? (
        <Button onClick={() => connect.mutate()} disabled={connect.isPending}>
          {t("payments.connectStripe")}
        </Button>
      ) : (
        <p className="text-sm">{t("payments.notConnected")}</p>
      )}
      <ErrorList error={connect.error ?? act.error} />
    </div>
  );
}

function RefundForm({ payment, onDone }: { payment: Payment; onDone: () => void }) {
  const { t } = useTranslation();
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [creditNote, setCreditNote] = useState(false);
  const refund = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/payments/{id}/refund", {
          params: { path: { id: payment.id } },
          body: { amount: amount || null, reason, credit_note: creditNote },
        }),
      ),
    onSuccess: onDone,
  });
  return (
    <form
      className="mt-2 flex flex-wrap items-end gap-2"
      aria-label={t("payments.refund")}
      onSubmit={(e) => {
        e.preventDefault();
        refund.mutate();
      }}
    >
      <TextField
        type="number"
        step="0.01"
        min={0}
        label={t("payments.refundAmount")}
        hint={t("payments.refundAll")}
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
      />
      <TextField
        label={t("payments.reason")}
        required
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4"
          checked={creditNote}
          onChange={(e) => setCreditNote(e.target.checked)}
        />
        {t("payments.creditInvoices")}
      </label>
      <Button type="submit" variant="danger" disabled={refund.isPending}>
        {t("payments.refund")}
      </Button>
      <ErrorList error={refund.error} />
    </form>
  );
}

/** Payments received (manual and online), with refunds (FR-11-4, FR-11-7). */
export function PaymentsList({ clientId }: { clientId?: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canRefund = usePermission("payments.payment.refund");
  const [refunding, setRefunding] = useState<string | null>(null);
  const list = useCursorList(["payments", clientId ?? "all"], async (cursor) =>
    unwrap(
      await api.GET("/api/v1/payments", {
        params: { query: { client: clientId, cursor } },
      }),
    ),
  );
  if (list.query.isPending) return <Spinner className="size-5" label={t("grid.loading")} />;
  if (!list.rows.length) return <p className="text-sm text-muted-foreground">{t("grid.empty")}</p>;
  return (
    <ul className="divide-y divide-border rounded-md border border-border text-sm">
      {list.rows.map((p) => (
        <li key={p.id} className="p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>
              {p.received_at ? formatDate(p.received_at, i18n.language) : "—"} ·{" "}
              {clientId ? "" : `${p.client_name} · `}
              {t(`payments.methods.${p.method}`)}
              {p.reference ? ` · ${p.reference}` : ""}
            </span>
            <span className="flex items-center gap-2">
              <strong>{formatMoney(p.amount, i18n.language)}</strong>
              <span className="text-muted-foreground">{t(`payments.status.${p.status}`)}</span>
              {canRefund && (p.status === "succeeded" || p.status === "partially_refunded") ? (
                <Button size="sm" variant="ghost" onClick={() => setRefunding(p.id)}>
                  {t("payments.refund")}
                </Button>
              ) : null}
              <a
                className="underline-offset-2 hover:underline"
                href={`/api/v1/payments/${p.id}/receipt`}
                target="_blank"
                rel="noreferrer"
              >
                {t("payments.receipt")}
              </a>
            </span>
          </div>
          {refunding === p.id ? (
            <RefundForm
              payment={p}
              onDone={() => {
                setRefunding(null);
                void queryClient.invalidateQueries({ queryKey: ["payments"] });
              }}
            />
          ) : null}
        </li>
      ))}
    </ul>
  );
}
