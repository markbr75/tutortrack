import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  FigureStrip,
  NamePlate,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  Spinner,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api } from "../api";
import { PanelEmpty, PortalHeader, Word } from "../layout/PortalPage";
import { isPositive } from "../money";

type MoneyValue = { amount: string; currency: string };
type Billing = components["schemas"]["PortalBilling"];
type Invoice = Billing["invoices"][number];

const quiet = "text-muted-foreground hover:text-foreground";

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
  const list = data?.methods ?? [];
  return (
    <section aria-labelledby={`methods-${clientId}`} className="border-t border-border">
      <h3 id={`methods-${clientId}`} className="px-5 pt-3.5 pb-1 text-sm font-semibold">
        {t("portal.paymentMethods")}
      </h3>
      {list.length ? (
        <PanelRows>
          {list.map((m) => (
            <PanelRow key={m.id}>
              <NamePlate
                name={
                  m.type === "card"
                    ? t("portal.card", { brand: m.brand, last4: m.last4 })
                    : t("portal.debit", { last4: m.last4 })
                }
                context={m.is_default ? t("portal.default") : undefined}
                aside={
                  <>
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
                      className={quiet}
                      onClick={() => act.mutate({ action: "remove", method: m.id })}
                    >
                      {t("portal.remove")}
                      <span className="sr-only"> {m.last4}</span>
                    </Button>
                  </>
                }
              />
            </PanelRow>
          ))}
        </PanelRows>
      ) : null}
      <p className="px-5 pt-1 pb-3 text-sm text-muted-foreground">
        {data?.auto_pay
          ? t("portal.autopayOn", {
              date: data.consent_given_at ? formatDate(data.consent_given_at, i18n.language) : "",
            })
          : t("portal.autopayOff")}
      </p>
      {act.error ? (
        <div className="px-5 pb-3">
          <Alert tone="danger">{act.error.message}</Alert>
        </div>
      ) : null}
      <PanelFooter>
        <Button size="sm" variant="secondary" onClick={() => act.mutate({ action: "add" })}>
          {t("portal.addMethod")}
        </Button>
        {data?.auto_pay ? (
          <Button
            size="sm"
            variant="ghost"
            className={quiet}
            onClick={() => act.mutate({ action: "autopay_off" })}
          >
            {t("portal.turnOffAutopay")}
          </Button>
        ) : null}
      </PanelFooter>
    </section>
  );
}

/** One household account: what is owed (with what is overdue said under it), credit, the
 * statement and how it pays. */
function Account({ account }: { account: Billing["accounts"][number] }) {
  const { t, i18n } = useTranslation();
  const money = (v: MoneyValue) => formatMoney(v, i18n.language);
  const overdue = isPositive(account.balances.overdue.amount);
  return (
    <RuledPanel
      title={account.name}
      flush
      aside={
        <a
          className="font-medium text-link underline-offset-2 hover:underline"
          href={`/api/v1/portal/statement?client=${account.client}`}
          target="_blank"
          rel="noreferrer"
        >
          {t("portal.statement")}
        </a>
      }
    >
      <div className="px-5">
        <FigureStrip
          className="border-y-0"
          label={account.name}
          figures={[
            {
              key: "owed",
              label: t("portal.owed"),
              value: money(account.balances.invoice_balance),
              note: overdue
                ? t("designS10.overdueOfIt", { amount: money(account.balances.overdue) })
                : t("designS10.nothingOverdue"),
              tone: overdue ? "margin" : "default",
            },
            {
              key: "credit",
              label: t("portal.credit"),
              value: money(account.balances.available_credit),
            },
          ]}
        />
      </div>
      <Methods clientId={account.client} />
    </RuledPanel>
  );
}

function isOverdue(inv: Invoice, today: string): boolean {
  return isPositive(inv.balance_due.amount) && Boolean(inv.due_date) && inv.due_date! < today;
}

/** An invoice's state in words: overdue in margin red, closed in faded ink. */
function InvoiceWord({ inv, today }: { inv: Invoice; today: string }) {
  const { t } = useTranslation();
  if (isOverdue(inv, today)) return <Word tone="margin">{t("portal.overdue")}</Word>;
  return (
    <Word tone={inv.status === "written_off" ? "muted" : "ink"}>
      {t(`portal.invoiceStatus.${inv.status}`)}
    </Word>
  );
}

/** A ruled row: primary line and one caption on the left, a fixed amount column, then the
 * row's actions (under the text on phones). */
function MoneyRow({
  primary,
  caption,
  amount,
  actions,
}: {
  primary: ReactNode;
  caption?: ReactNode;
  amount: string;
  actions?: ReactNode;
}) {
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-5 py-2.5 sm:grid-cols-[minmax(0,1fr)_8rem_auto]">
      <div className="min-w-0">
        <p className="font-medium">{primary}</p>
        {caption ? <p className="text-xs text-muted-foreground">{caption}</p> : null}
      </div>
      <p className="text-right font-semibold whitespace-nowrap tabular-nums sm:w-32">{amount}</p>
      {actions ? (
        <div className="col-span-2 flex flex-wrap gap-2 sm:col-span-1 sm:justify-end">
          {actions}
        </div>
      ) : (
        <span className="hidden sm:block" />
      )}
    </li>
  );
}

/** Package balances and packages on sale online (FR-15-7, E10-T12). */
function Packages({ billing }: { billing: Billing }) {
  const { t, i18n } = useTranslation();
  const [client, setClient] = useState(billing.accounts[0]?.client ?? "");
  const buy = useMutation({
    mutationFn: async (template: string) =>
      unwrap(await api.POST("/api/v1/portal/packages", { body: { client, template } })),
    onSuccess: (result) => {
      if (result.pay_token) window.location.assign(`/pay/${result.pay_token}`);
    },
  });
  const packages = billing.packages ?? [];
  const offers = billing.package_offers ?? [];
  if (!packages.length && !offers.length) return null;
  return (
    <RuledPanel title={t("portalPackages.title")} flush>
      {packages.length ? (
        <PanelRows>
          {packages.map((p) => (
            <PanelRow key={p.id}>
              <p className="font-medium">{p.name}</p>
              <p className="text-xs text-muted-foreground tabular-nums">
                {[
                  p.student_name,
                  t(`portalPackages.left.${p.quantity_type}`, {
                    left: Number(p.units_remaining),
                    total: Number(p.units_total),
                  }),
                  p.status === "pending" ? t("portalPackages.awaitingPayment") : "",
                  p.expires_at
                    ? t("portalPackages.expires", {
                        date: formatDate(p.expires_at, i18n.language),
                      })
                    : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </PanelRow>
          ))}
        </PanelRows>
      ) : (
        <PanelEmpty>{t("portalPackages.none")}</PanelEmpty>
      )}
      {offers.length ? (
        <section aria-labelledby="buy-package" className="border-t border-border">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-5 pt-3.5 pb-1">
            <h3 id="buy-package" className="text-sm font-semibold">
              {t("portalPackages.buy")}
            </h3>
            {billing.accounts.length > 1 ? (
              <SelectField
                size="sm"
                label={t("portalPackages.forAccount")}
                hideLabel
                value={client}
                onChange={(e) => setClient(e.target.value)}
                options={billing.accounts.map((a) => ({ value: a.client, label: a.name }))}
              />
            ) : null}
          </div>
          <ul className="divide-y divide-rule">
            {offers.map((offer) => (
              <MoneyRow
                key={offer.id}
                primary={offer.name}
                caption={offer.description || undefined}
                amount={formatMoney(offer.price, i18n.language)}
                actions={
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => buy.mutate(offer.id)}
                    disabled={buy.isPending}
                  >
                    {t("portalPackages.buyNow")}
                  </Button>
                }
              />
            ))}
          </ul>
          {buy.error ? (
            <div className="px-5 pb-4">
              <Alert tone="danger">{t("portalPackages.failed")}</Alert>
            </div>
          ) : null}
        </section>
      ) : null}
    </RuledPanel>
  );
}

/** Balances, invoices to pay, top-up requests, packages, credit notes, statements and
 * payment methods (FR-15-7). Paying opens the hosted pay page. */
export function BillingPage() {
  const { t, i18n } = useTranslation();
  const data = useQuery({
    queryKey: ["portal", "billing"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/billing")),
  });
  if (data.isPending) return <Spinner label={t("grid.loading")} />;
  const b = data.data;
  if (!b) return <Alert tone="danger">{t("errors.generic")}</Alert>;
  const money = (v: MoneyValue) => formatMoney(v, i18n.language);
  const date = (iso: string) => formatDate(iso, i18n.language);
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div className="space-y-6">
      <PortalHeader title={t("portal.nav.billing")} />
      {b.accounts.map((account) => (
        <Account key={account.client} account={account} />
      ))}
      <RuledPanel title={t("portal.invoices")} flush>
        {b.invoices.length ? (
          <ul className="divide-y divide-rule">
            {b.invoices.map((inv) => (
              <MoneyRow
                key={inv.id}
                primary={<span className="tabular-nums">{inv.number}</span>}
                caption={
                  <>
                    <span className="tabular-nums">
                      {[
                        inv.issue_date
                          ? t("designS10.issuedOn", { date: date(inv.issue_date) })
                          : "",
                        inv.due_date ? t("designS10.dueOn", { date: date(inv.due_date) }) : "",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    {inv.issue_date || inv.due_date ? " · " : ""}
                    <InvoiceWord inv={inv} today={today} />
                  </>
                }
                amount={money(inv.total)}
                actions={
                  <>
                    <a
                      className="inline-flex h-8 items-center text-sm font-medium text-link underline-offset-2 hover:underline"
                      href={`/api/v1/pay/${inv.pdf_token}/pdf`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t("portal.pdf")}
                      <span className="sr-only"> {inv.number}</span>
                    </a>
                    {inv.pay_token ? (
                      <a className={buttonClass({ size: "sm" })} href={`/pay/${inv.pay_token}`}>
                        {t("portal.payAmount", { amount: money(inv.balance_due) })}
                      </a>
                    ) : null}
                  </>
                }
              />
            ))}
          </ul>
        ) : (
          <PanelEmpty>{t("portal.noInvoices")}</PanelEmpty>
        )}
      </RuledPanel>
      {b.payment_requests.length ? (
        <RuledPanel title={t("portal.topUps")} flush>
          <ul className="divide-y divide-rule">
            {b.payment_requests.map((r) => (
              <MoneyRow
                key={r.id}
                primary={<span className="tabular-nums">{r.number}</span>}
                caption={r.description}
                amount={money(r.amount)}
                actions={
                  <a className={buttonClass({ size: "sm" })} href={`/pay/${r.pay_token}`}>
                    {t("portal.pay")}
                  </a>
                }
              />
            ))}
          </ul>
        </RuledPanel>
      ) : null}
      <Packages billing={b} />
      {b.credit_notes.length ? (
        <RuledPanel title={t("portal.creditNotes")} flush>
          <ul className="divide-y divide-rule">
            {b.credit_notes.map((n) => (
              <MoneyRow
                key={n.id}
                primary={<span className="tabular-nums">{n.number}</span>}
                caption={t("designS10.forInvoice", { number: n.invoice_number })}
                amount={money(n.total)}
              />
            ))}
          </ul>
        </RuledPanel>
      ) : null}
    </div>
  );
}
