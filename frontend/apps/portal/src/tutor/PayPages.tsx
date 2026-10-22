import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  figureCell,
  FigureStrip,
  PanelFooter,
  RuledPanel,
  RuledTable,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";

import { api, uploadFile } from "../api";
import { FileField, PanelEmpty, PortalHeader, Word } from "../layout/PortalPage";
import { AnnualEarnings } from "./G3Pages";
import { MyUsTaxInfo } from "./Phase3";

type Totals = Record<string, string>;

function TotalsLine({ totals }: { totals: Totals }) {
  const { i18n } = useTranslation();
  const parts = Object.entries(totals).map(([currency, amount]) =>
    formatMoney({ amount, currency }, i18n.language),
  );
  return <>{parts.length ? parts.join(" + ") : formatMoney({ amount: "0", currency: "GBP" })}</>;
}

/** A pay item's title without the raw ISO date the server appends ("… · 2026-10-19"); the
 * date is shown once, formatted, in the caption. */
function payTitle(description: string): string {
  return description.replace(/\s*·\s*\d{4}-\d{2}-\d{2}$/, "");
}

/** A ruled row with a primary line, one caption and a fixed amount column. */
function AmountRow({
  primary,
  caption,
  amount,
}: {
  primary: ReactNode;
  caption?: ReactNode;
  amount: string;
}) {
  return (
    <li className="flex items-baseline justify-between gap-4 px-5 py-2.5 text-sm">
      <div className="min-w-0">
        <p className="font-medium">{primary}</p>
        {caption ? <div className="text-xs text-muted-foreground">{caption}</div> : null}
      </div>
      <p className="w-28 shrink-0 text-right font-semibold whitespace-nowrap tabular-nums">
        {amount}
      </p>
    </li>
  );
}

/** Pay to come, held pay with what releases it, payouts and statements (FR-12-9). */
export function EarningsPage() {
  const { t, i18n } = useTranslation();
  const earnings = useQuery({
    queryKey: ["tutor", "my-earnings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/earnings")),
  });
  if (!earnings.data) return <Spinner label={t("grid.loading")} />;
  const e = earnings.data;
  const money = (v: { amount: string; currency: string }) => formatMoney(v, i18n.language);
  const date = (iso: string) => formatDate(iso, i18n.language);
  return (
    <div>
      <PortalHeader title={t("tutor.nav.earnings")} description={t("tutor.provisional")} />
      <div className="space-y-6">
        <FigureStrip
          label={t("tutor.nav.earnings")}
          figures={[
            {
              key: "upcoming",
              label: t("pay.upcoming"),
              value: <TotalsLine totals={e.upcoming_total} />,
            },
            {
              key: "ytd",
              label: t("pay.yearToDate"),
              value: <TotalsLine totals={e.year_to_date} />,
            },
          ]}
        />
        {e.held.length ? (
          // Held pay waits on the tutor (a report to write, documents to update).
          <RuledPanel
            title={t("pay.held")}
            rule="margin"
            aside={<span className="font-semibold text-margin tabular-nums">{e.held.length}</span>}
            flush
          >
            <ul className="divide-y divide-rule">
              {e.held.map((item) => (
                <AmountRow
                  key={item.id}
                  primary={payTitle(item.description)}
                  caption={(item.hold_reasons as string[]).map((reason, n) => (
                    <p key={reason}>
                      {n === 0 ? <span className="tabular-nums">{date(item.date)} · </span> : null}
                      {t(`pay.holdReasons.${reason}`)}
                    </p>
                  ))}
                  amount={money(item.amount)}
                />
              ))}
            </ul>
          </RuledPanel>
        ) : null}
        <RuledPanel title={t("pay.upcomingItems")} flush>
          <RuledTable
            caption={t("pay.upcomingItems")}
            columns={[
              { key: "what", header: t("g3.tutorReview.lesson") },
              { key: "amount", header: t("pay.amount"), end: true, width: "w-28" },
            ]}
            empty={e.upcoming.length ? undefined : t("designS10.nothingToCome")}
          >
            {e.upcoming.map((item) => (
              <tr key={item.id}>
                <td>
                  <span className="font-medium">{payTitle(item.description)}</span>
                  <span className="block text-xs text-muted-foreground tabular-nums">
                    {date(item.date)}
                  </span>
                </td>
                <td className={figureCell}>{money(item.amount)}</td>
              </tr>
            ))}
          </RuledTable>
        </RuledPanel>
        <RuledPanel title={t("pay.history")} flush>
          {e.payouts.length || e.statements.length ? (
            <ul className="divide-y divide-rule">
              {e.payouts.map((payout) => (
                <AmountRow
                  key={payout.id}
                  primary={
                    <span className="tabular-nums">
                      {payout.paid_at ? date(payout.paid_at) : t("designS10.payout")}
                    </span>
                  }
                  caption={t("designS10.payout")}
                  amount={money(payout.amount)}
                />
              ))}
              {e.statements.map((statement) => (
                <AmountRow
                  key={statement.id}
                  primary={
                    <a
                      className="text-link underline-offset-2 hover:underline"
                      href={`/api/v1/pay-statements/${statement.id}/pdf`}
                    >
                      {t(`pay.statementKinds.${statement.kind}`)} {statement.number}
                    </a>
                  }
                  caption={
                    statement.issued_at ? (
                      <span className="tabular-nums">{date(statement.issued_at)}</span>
                    ) : undefined
                  }
                  amount={money(statement.total)}
                />
              ))}
            </ul>
          ) : (
            <PanelEmpty>{t("designS10.noPayouts")}</PanelEmpty>
          )}
        </RuledPanel>
        <AnnualEarnings />
        <MyUsTaxInfo />
      </div>
    </div>
  );
}

type Category = components["schemas"]["ExpenseCategory"];

/** Expense and mileage claims with a receipt photo (FR-12-3/4, E16-T06). */
export function ExpensesPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [category, setCategory] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [distance, setDistance] = useState("");
  const [receipt, setReceipt] = useState<File | null>(null);
  const categories = useQuery({
    queryKey: ["expense-categories"],
    queryFn: async () => unwrap(await api.GET("/api/v1/expense-categories")),
  });
  const claims = useQuery({
    queryKey: ["tutor", "expenses"],
    queryFn: async () => unwrap(await api.GET("/api/v1/expenses")),
  });
  const chosen: Category | undefined = categories.data?.find((c) => c.id === category);
  const mileage = chosen?.kind === "mileage";
  const suggest = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.GET("/api/v1/expenses/mileage-suggestions", {
          params: { query: { date, unit: chosen?.distance_unit ?? "mi" } },
        }),
      ),
    onSuccess: (legs) => {
      const total = legs.reduce((sum, leg) => sum + Number(leg.distance), 0);
      setDistance(total ? total.toFixed(1) : "");
      if (legs.length) setDescription(legs.map((l) => `${l.origin} → ${l.destination}`).join(", "));
    },
  });
  const submit = useMutation({
    mutationFn: async () => {
      const receiptId = receipt ? await uploadFile(receipt) : null;
      return unwrap(
        await api.POST("/api/v1/expenses", {
          body: {
            category,
            date,
            description,
            amount: mileage ? null : { amount, currency: "GBP" }, // the server uses your pay currency
            distance: mileage ? distance : null,
            receipt: receiptId,
          },
        }),
      );
    },
    onSuccess: () => {
      setDescription("");
      setAmount("");
      setDistance("");
      setReceipt(null);
      void queryClient.invalidateQueries({ queryKey: ["tutor", "expenses"] });
    },
  });
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit.mutate();
  };
  const rows = claims.data?.results ?? [];
  return (
    <div>
      <PortalHeader title={t("pay.expenses")} />
      <div className="space-y-6">
        <form onSubmit={onSubmit} aria-label={t("pay.newClaim")}>
          <RuledPanel title={t("pay.newClaim")} flush>
            <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
              <SelectField
                label={t("pay.category")}
                required
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                options={[
                  { value: "", label: t("pay.chooseCategory") },
                  ...(categories.data ?? []).map((c) => ({ value: c.id, label: c.name })),
                ]}
              />
              <TextField
                label={t("pay.date")}
                className="tabular-nums"
                type="date"
                required
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
              <div className="sm:col-span-2">
                <TextField
                  label={t("pay.description")}
                  required
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
              {mileage ? (
                <div className="flex flex-wrap items-end gap-2">
                  <TextField
                    className="w-32 text-right tabular-nums"
                    label={t("pay.distance", { unit: chosen?.distance_unit ?? "mi" })}
                    inputMode="decimal"
                    required
                    value={distance}
                    onChange={(e) => setDistance(e.target.value)}
                  />
                  <Button
                    type="button"
                    variant="secondary"
                    className="h-10"
                    onClick={() => suggest.mutate()}
                  >
                    {t("pay.suggestDistance")}
                  </Button>
                </div>
              ) : (
                <TextField
                  className="w-32 text-right tabular-nums"
                  label={t("pay.amount")}
                  inputMode="decimal"
                  required
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
              )}
              <FileField
                label={t("pay.receipt")}
                accept="image/*,application/pdf"
                capture="environment"
                onChange={(e) => setReceipt(e.target.files?.[0] ?? null)}
              />
            </div>
            {submit.error ? (
              <div className="px-5 pb-4">
                <Alert tone="danger">{submit.error.message}</Alert>
              </div>
            ) : null}
            <PanelFooter>
              <Button type="submit" disabled={submit.isPending}>
                {t("pay.submitClaim")}
              </Button>
              <span role="status" className="text-sm text-success">
                {submit.isSuccess ? t("pay.claimSent") : ""}
              </span>
            </PanelFooter>
          </RuledPanel>
        </form>
        <RuledPanel title={t("designS10.yourClaims")} flush>
          {rows.length ? (
            <ul className="divide-y divide-rule">
              {rows.map((claim) => (
                <AmountRow
                  key={claim.id}
                  primary={claim.description}
                  caption={
                    <>
                      <span className="tabular-nums">{formatDate(claim.date, i18n.language)}</span>{" "}
                      ·{" "}
                      <Word
                        tone={
                          claim.status === "submitted"
                            ? "margin"
                            : claim.status === "draft"
                              ? "muted"
                              : "ink"
                        }
                        className={
                          claim.status === "approved" || claim.status === "rejected"
                            ? "text-foreground"
                            : ""
                        }
                      >
                        {t(`pay.claimStatus.${claim.status}`)}
                      </Word>
                      {claim.decision_comment ? ` · ${claim.decision_comment}` : ""}
                    </>
                  }
                  amount={formatMoney(claim.amount, i18n.language)}
                />
              ))}
            </ul>
          ) : (
            <PanelEmpty>{t("designS10.noClaims")}</PanelEmpty>
          )}
        </RuledPanel>
      </div>
    </div>
  );
}

/** Bank details, the self-billing agreement and Stripe payout setup (FR-12-2, E16-T07). */
export function PayDetailsSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const profile = useQuery({
    queryKey: ["tutor", "pay-profile"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/pay-profile")),
  });
  const [bank, setBank] = useState({ account_name: "", sort_code: "", account_number: "" });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["tutor", "pay-profile"] });
  const saveBank = useMutation({
    mutationFn: async () =>
      unwrap(await api.PUT("/api/v1/me/pay-profile", { body: { country: "GB", ...bank } })),
    onSuccess: refresh,
  });
  const agree = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/me/pay-profile/self-billing")),
    onSuccess: refresh,
  });
  const stripe = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/me/pay-profile/stripe")),
    onSuccess: (r) => window.location.assign(r.url),
  });
  if (!profile.data) return null;
  const p = profile.data;
  return (
    <form
      aria-labelledby="pay-details"
      onSubmit={(e) => {
        e.preventDefault();
        saveBank.mutate();
      }}
    >
      <RuledPanel
        title={t("pay.details")}
        titleId="pay-details"
        description={p.bank_hint ? t("pay.bankOnFile", { hint: p.bank_hint }) : t("pay.noBank")}
        flush
      >
        <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-3">
          <TextField
            label={t("pay.accountName")}
            value={bank.account_name}
            onChange={(e) => setBank({ ...bank, account_name: e.target.value })}
          />
          <TextField
            label={t("pay.sortCode")}
            className="tabular-nums"
            inputMode="numeric"
            value={bank.sort_code}
            onChange={(e) => setBank({ ...bank, sort_code: e.target.value })}
          />
          <TextField
            label={t("pay.accountNumber")}
            className="tabular-nums"
            inputMode="numeric"
            value={bank.account_number}
            onChange={(e) => setBank({ ...bank, account_number: e.target.value })}
          />
        </div>
        {saveBank.error ? (
          <div className="px-5 pb-4">
            <Alert tone="danger">{saveBank.error.message}</Alert>
          </div>
        ) : null}
        {p.employment_type === "self_employed" ? (
          <div className="space-y-2 border-t border-rule px-5 py-3 text-sm">
            {p.self_billing_agreed_at ? (
              <p>{t("pay.selfBillingAgreed")}</p>
            ) : (
              <>
                <p className="text-muted-foreground">{t("pay.selfBillingText")}</p>
                <Button type="button" size="sm" variant="secondary" onClick={() => agree.mutate()}>
                  {t("pay.agreeSelfBilling")}
                </Button>
              </>
            )}
          </div>
        ) : null}
        <PanelFooter>
          {p.method === "stripe_connect" && !p.stripe_payouts_enabled ? (
            <Button type="button" variant="secondary" onClick={() => stripe.mutate()}>
              {t("pay.setUpStripe")}
            </Button>
          ) : null}
          <Button type="submit" variant="secondary" disabled={saveBank.isPending}>
            {t("pay.saveBank")}
          </Button>
        </PanelFooter>
      </RuledPanel>
    </form>
  );
}
