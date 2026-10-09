import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";

type MoneyValue = { amount: string; currency: string };

function Methods({ clientId }: { clientId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const key = ["portal", "methods", clientId];
  const methods = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/portal/payment-methods", {
          params: { query: { client: clientId } },
        }),
      ),
  });
  const act = useMutation({
    mutationFn: async (body: {
      action: "add" | "default" | "remove" | "autopay_off";
      method?: string;
    }) =>
      unwrap(
        await api.POST("/api/v1/portal/payment-methods", { body: { client: clientId, ...body } }),
      ),
    onSuccess: (result) => {
      if (result.url) window.location.assign(result.url);
      else void queryClient.invalidateQueries({ queryKey: key });
    },
  });
  const data = methods.data;
  return (
    <section aria-labelledby={`methods-${clientId}`} className="space-y-2">
      <h3 id={`methods-${clientId}`} className="font-semibold">
        {t("portal.paymentMethods")}
      </h3>
      <ul className="space-y-1 text-sm">
        {(data?.methods ?? []).map((m) => (
          <li key={m.id} className="flex flex-wrap items-center gap-2">
            {m.type === "card"
              ? t("portal.card", { brand: m.brand, last4: m.last4 })
              : t("portal.debit", { last4: m.last4 })}
            {m.is_default ? ` · ${t("portal.default")}` : ""}
            {!m.is_default ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => act.mutate({ action: "default", method: m.id })}
              >
                {t("portal.makeDefault")}
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => act.mutate({ action: "remove", method: m.id })}
            >
              {t("portal.remove")}
              <span className="sr-only"> {m.last4}</span>
            </Button>
          </li>
        ))}
      </ul>
      <p className="text-sm">
        {data?.auto_pay
          ? t("portal.autopayOn", {
              date: data.consent_given_at ? formatDate(data.consent_given_at, i18n.language) : "",
            })
          : t("portal.autopayOff")}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => act.mutate({ action: "add" })}>
          {t("portal.addMethod")}
        </Button>
        {data?.auto_pay ? (
          <Button size="sm" variant="ghost" onClick={() => act.mutate({ action: "autopay_off" })}>
            {t("portal.turnOffAutopay")}
          </Button>
        ) : null}
      </div>
      {act.error ? <Alert tone="danger">{act.error.message}</Alert> : null}
    </section>
  );
}

/** Balances, invoices to pay, top-up requests, credit notes, statements and payment
 * methods (FR-15-7). Paying opens the hosted pay page. */
export function BillingPage() {
  const { t, i18n } = useTranslation();
  const data = useQuery({
    queryKey: ["portal", "billing"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/billing")),
  });
  if (data.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  const b = data.data;
  if (!b) return null;
  const money = (v: MoneyValue) => formatMoney(v, i18n.language);
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">{t("portal.nav.billing")}</h1>
      {b.accounts.map((acct) => (
        <section
          key={acct.client}
          aria-label={acct.name}
          className="space-y-3 rounded-lg border border-border p-4"
        >
          <h2 className="font-semibold">{acct.name}</h2>
          <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">{t("portal.owed")}</dt>
              <dd className="text-lg font-semibold">{money(acct.balances.invoice_balance)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("portal.overdue")}</dt>
              <dd className="text-lg font-semibold">{money(acct.balances.overdue)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("portal.credit")}</dt>
              <dd className="text-lg font-semibold">{money(acct.balances.available_credit)}</dd>
            </div>
          </dl>
          <a
            className="text-sm underline-offset-2 hover:underline"
            href={`/api/v1/portal/statement?client=${acct.client}`}
            target="_blank"
            rel="noreferrer"
          >
            {t("portal.statement")}
          </a>
          <Methods clientId={acct.client} />
        </section>
      ))}
      {b.payment_requests.length ? (
        <section aria-labelledby="requests" className="space-y-2">
          <h2 id="requests" className="font-semibold">
            {t("portal.topUps")}
          </h2>
          {b.payment_requests.map((r) => (
            <p key={r.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>
                {r.number} · {r.description} · {money(r.amount)}
              </span>
              <a
                className="rounded-md bg-primary px-3 py-1.5 text-primary-foreground"
                href={`/pay/${r.pay_token}`}
              >
                {t("portal.pay")}
              </a>
            </p>
          ))}
        </section>
      ) : null}
      <section aria-labelledby="invoices" className="space-y-2">
        <h2 id="invoices" className="font-semibold">
          {t("portal.invoices")}
        </h2>
        {!b.invoices.length ? (
          <p className="text-sm text-muted-foreground">{t("portal.noInvoices")}</p>
        ) : null}
        <ul className="divide-y divide-border rounded-lg border border-border text-sm">
          {b.invoices.map((inv) => (
            <li key={inv.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
              <span>
                {inv.number} · {inv.issue_date ? formatDate(inv.issue_date, i18n.language) : ""} ·{" "}
                {money(inv.total)} · {t(`portal.invoiceStatus.${inv.status}`)}
              </span>
              <span className="flex gap-2">
                <a
                  className="underline-offset-2 hover:underline"
                  href={`/api/v1/pay/${inv.pdf_token}/pdf`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("portal.pdf")}
                  <span className="sr-only"> {inv.number}</span>
                </a>
                {inv.pay_token ? (
                  <a
                    className="rounded-md bg-primary px-3 py-1 text-primary-foreground"
                    href={`/pay/${inv.pay_token}`}
                  >
                    {t("portal.payAmount", { amount: money(inv.balance_due) })}
                  </a>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      </section>
      {b.credit_notes.length ? (
        <section aria-labelledby="credits" className="space-y-2">
          <h2 id="credits" className="font-semibold">
            {t("portal.creditNotes")}
          </h2>
          <ul className="text-sm">
            {b.credit_notes.map((n) => (
              <li key={n.id}>
                {n.number} · {n.invoice_number} · {money(n.total)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
