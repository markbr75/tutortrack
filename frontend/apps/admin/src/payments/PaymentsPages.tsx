import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  PageHeader,
  PanelFooter,
  RuledPanel,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { SyncBadge } from "../accounting/SyncBadge";
import { useSyncStatuses } from "../accounting/useSyncStatuses";
import { PanelEmpty, PanelLoading, rowClass } from "../billing/moneyUi";
import { ErrorList } from "../calendar/ErrorList";
import { PaymentOptions } from "../g3/PaymentOptions";
import { useCursorList } from "../lists";
import { PartnerProviders } from "./PartnerProviders";

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
    <section className="max-w-3xl">
      <PageHeader title={t("payments.settingsTitle")} description={t("payments.settingsHelp")} />
      <div className="space-y-6">
        {providers.isPending ? (
          <Spinner label={t("grid.loading")} />
        ) : stripe ? (
          <RuledPanel
            title="Stripe"
            aside={
              // Setup still waiting on the business reads in margin red; other states stay quiet.
              <span
                className={
                  stripe.status === "pending" || stripe.status === "restricted"
                    ? "font-semibold text-margin"
                    : "text-muted-foreground"
                }
              >
                {t(`payments.accountStatus.${stripe.status}`)}
              </span>
            }
            footer={
              canManage ? (
                <>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => act.mutate({ id: stripe.id, kind: "disconnect" })}
                  >
                    {t("payments.disconnect")}
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => act.mutate({ id: stripe.id, kind: "refresh" })}
                  >
                    {t("payments.checkStatus")}
                  </Button>
                  {stripe.status !== "active" ? (
                    <Button size="sm" onClick={() => connect.mutate()}>
                      {t("payments.finishSetup")}
                    </Button>
                  ) : null}
                </>
              ) : undefined
            }
          >
            <p className="text-sm tabular-nums">{stripe.account_ref}</p>
            {stripe.requirements.length ? (
              <Alert tone="warning" className="mt-3">
                {t("payments.requirements")}
              </Alert>
            ) : null}
          </RuledPanel>
        ) : (
          <RuledPanel
            title="Stripe"
            footer={
              canManage ? (
                <Button onClick={() => connect.mutate()} disabled={connect.isPending}>
                  {t("payments.connectStripe")}
                </Button>
              ) : undefined
            }
          >
            <p className="text-sm text-muted-foreground">{t("payments.notConnected")}</p>
          </RuledPanel>
        )}
        <ErrorList error={connect.error ?? act.error} />
        <PartnerProviders />
        <PaymentOptions />
      </div>
    </section>
  );
}

function RefundForm({
  payment,
  onDone,
  onCancel,
}: {
  payment: Payment;
  onDone: () => void;
  onCancel: () => void;
}) {
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
      className="mt-3 space-y-3 border-t border-rule pt-3"
      aria-label={t("payments.refund")}
      onSubmit={(e) => {
        e.preventDefault();
        refund.mutate();
      }}
    >
      <div className="grid max-w-2xl gap-3 sm:grid-cols-[12rem_minmax(0,1fr)]">
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
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4"
          checked={creditNote}
          onChange={(e) => setCreditNote(e.target.checked)}
        />
        {t("payments.creditInvoices")}
      </label>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="danger" disabled={refund.isPending}>
          {t("payments.refund")}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
      </div>
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
  const synced = useSyncStatuses(
    "payment",
    list.rows.map((p) => p.id),
  );
  return (
    <section
      aria-label={t("payments.title")}
      className="rounded-xl border border-border bg-surface text-sm"
    >
      {list.query.isPending ? (
        <PanelLoading label={t("grid.loading")} />
      ) : !list.rows.length ? (
        <PanelEmpty>{t("designS7.payments.none")}</PanelEmpty>
      ) : (
        <ul>
          {list.rows.map((p) => (
            <li key={p.id} className={rowClass}>
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <div className="min-w-0">
                  <p className="font-medium">
                    {clientId ? t(`payments.methods.${p.method}`) : p.client_name}
                  </p>
                  <p className="text-xs text-muted-foreground tabular-nums">
                    {[
                      p.received_at ? formatDate(p.received_at, i18n.language) : "—",
                      clientId ? "" : t(`payments.methods.${p.method}`),
                      p.reference,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>
                <div className="ml-auto flex flex-wrap items-center justify-end gap-x-4 gap-y-1">
                  <div className="text-right">
                    <p className="font-semibold tabular-nums">
                      {formatMoney(p.amount, i18n.language)}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {t(`payments.status.${p.status}`)}
                      {synced.data?.[p.id] ? " · " : ""}
                      <SyncBadge record={synced.data?.[p.id]} />
                    </p>
                  </div>
                  <div className="flex items-center gap-1">
                    {canRefund &&
                    (p.status === "succeeded" || p.status === "partially_refunded") ? (
                      <Button size="sm" variant="ghost" onClick={() => setRefunding(p.id)}>
                        {t("payments.refund")}
                      </Button>
                    ) : null}
                    <a
                      className={buttonClass({ variant: "ghost", size: "sm" })}
                      href={`/api/v1/payments/${p.id}/receipt`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t("payments.receipt")}
                    </a>
                  </div>
                </div>
              </div>
              {refunding === p.id ? (
                <RefundForm
                  payment={p}
                  onCancel={() => setRefunding(null)}
                  onDone={() => {
                    setRefunding(null);
                    void queryClient.invalidateQueries({ queryKey: ["payments"] });
                  }}
                />
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {list.query.hasNextPage ? (
        <PanelFooter className="justify-center">
          <Button
            size="sm"
            variant="ghost"
            loading={list.query.isFetchingNextPage}
            onClick={() => void list.query.fetchNextPage()}
          >
            {t("grid.loadMore")}
          </Button>
        </PanelFooter>
      ) : null}
    </section>
  );
}
