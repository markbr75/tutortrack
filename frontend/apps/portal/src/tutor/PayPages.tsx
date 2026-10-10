import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, uploadFile } from "../api";

type Totals = Record<string, string>;

function TotalsLine({ totals }: { totals: Totals }) {
  const { i18n } = useTranslation();
  const parts = Object.entries(totals).map(([currency, amount]) =>
    formatMoney({ amount, currency }, i18n.language),
  );
  return <>{parts.length ? parts.join(" + ") : formatMoney({ amount: "0", currency: "GBP" })}</>;
}

/** Pay to come, held pay with what releases it, payouts and statements (FR-12-9). */
export function EarningsPage() {
  const { t, i18n } = useTranslation();
  const earnings = useQuery({
    queryKey: ["tutor", "my-earnings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/earnings")),
  });
  if (!earnings.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const e = earnings.data;
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">{t("tutor.nav.earnings")}</h1>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-lg border border-border p-3">
          <dt className="text-muted-foreground">{t("pay.upcoming")}</dt>
          <dd className="text-lg font-semibold">
            <TotalsLine totals={e.upcoming_total} />
          </dd>
        </div>
        <div className="rounded-lg border border-border p-3">
          <dt className="text-muted-foreground">{t("pay.yearToDate")}</dt>
          <dd className="text-lg font-semibold">
            <TotalsLine totals={e.year_to_date} />
          </dd>
        </div>
      </dl>
      {e.held.length ? (
        <section aria-labelledby="held" className="space-y-2">
          <h2 id="held" className="font-semibold">
            {t("pay.held")}
          </h2>
          <ul className="divide-y divide-border rounded-lg border border-border text-sm">
            {e.held.map((item) => (
              <li key={item.id} className="space-y-1 p-3">
                <div className="flex justify-between gap-2">
                  <span>{item.description}</span>
                  <span>{formatMoney(item.amount, i18n.language)}</span>
                </div>
                {(item.hold_reasons as string[]).map((reason) => (
                  <p key={reason} className="text-xs text-muted-foreground">
                    {t(`pay.holdReasons.${reason}`)}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section aria-labelledby="upcoming" className="space-y-2">
        <h2 id="upcoming" className="font-semibold">
          {t("pay.upcomingItems")}
        </h2>
        <ul className="divide-y divide-border rounded-lg border border-border text-sm">
          {e.upcoming.map((item) => (
            <li key={item.id} className="flex justify-between gap-2 p-3">
              <span>
                {formatDate(item.date, i18n.language)} · {item.description}
              </span>
              <span>{formatMoney(item.amount, i18n.language)}</span>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="paid" className="space-y-2">
        <h2 id="paid" className="font-semibold">
          {t("pay.history")}
        </h2>
        <ul className="divide-y divide-border rounded-lg border border-border text-sm">
          {e.payouts.map((payout) => (
            <li key={payout.id} className="flex justify-between gap-2 p-3">
              <span>{payout.paid_at ? formatDate(payout.paid_at, i18n.language) : ""}</span>
              <span>{formatMoney(payout.amount, i18n.language)}</span>
            </li>
          ))}
          {e.statements.map((statement) => (
            <li key={statement.id} className="flex justify-between gap-2 p-3">
              <a className="underline" href={`/api/v1/pay-statements/${statement.id}/pdf`}>
                {t(`pay.statementKinds.${statement.kind}`)} {statement.number}
              </a>
              <span>{formatMoney(statement.total, i18n.language)}</span>
            </li>
          ))}
        </ul>
      </section>
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
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">{t("pay.expenses")}</h1>
      <form className="space-y-3" onSubmit={onSubmit} aria-label={t("pay.newClaim")}>
        <label className="block space-y-1 text-sm">
          <span className="font-medium">{t("pay.category")}</span>
          <select
            required
            className="block w-full rounded-md border border-border bg-background px-3 py-2"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">{t("pay.chooseCategory")}</option>
            {categories.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <TextField
          label={t("pay.date")}
          type="date"
          required
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
        <TextField
          label={t("pay.description")}
          required
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        {mileage ? (
          <div className="flex flex-wrap items-end gap-2">
            <TextField
              label={t("pay.distance", { unit: chosen?.distance_unit ?? "mi" })}
              inputMode="decimal"
              required
              value={distance}
              onChange={(e) => setDistance(e.target.value)}
            />
            <Button type="button" variant="secondary" size="sm" onClick={() => suggest.mutate()}>
              {t("pay.suggestDistance")}
            </Button>
          </div>
        ) : (
          <TextField
            label={t("pay.amount")}
            inputMode="decimal"
            required
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        )}
        <label className="block space-y-1 text-sm">
          <span className="font-medium">{t("pay.receipt")}</span>
          <input
            type="file"
            accept="image/*,application/pdf"
            capture="environment"
            onChange={(e) => setReceipt(e.target.files?.[0] ?? null)}
          />
        </label>
        <Button type="submit" disabled={submit.isPending}>
          {t("pay.submitClaim")}
        </Button>
        {submit.error ? <Alert tone="danger">{submit.error.message}</Alert> : null}
        {submit.isSuccess ? <p role="status">{t("pay.claimSent")}</p> : null}
      </form>
      <ul className="divide-y divide-border rounded-lg border border-border text-sm">
        {claims.data?.results.map((claim) => (
          <li key={claim.id} className="flex justify-between gap-2 p-3">
            <span>
              {formatDate(claim.date, i18n.language)} · {claim.description} ·{" "}
              {t(`pay.claimStatus.${claim.status}`)}
              {claim.decision_comment ? ` · ${claim.decision_comment}` : ""}
            </span>
            <span>{formatMoney(claim.amount, i18n.language)}</span>
          </li>
        ))}
      </ul>
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
    <section aria-labelledby="pay-details" className="space-y-3">
      <h2 id="pay-details" className="font-semibold">
        {t("pay.details")}
      </h2>
      <p className="text-sm">
        {p.bank_hint ? t("pay.bankOnFile", { hint: p.bank_hint }) : t("pay.noBank")}
      </p>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          saveBank.mutate();
        }}
      >
        <TextField
          label={t("pay.accountName")}
          value={bank.account_name}
          onChange={(e) => setBank({ ...bank, account_name: e.target.value })}
        />
        <TextField
          label={t("pay.sortCode")}
          inputMode="numeric"
          value={bank.sort_code}
          onChange={(e) => setBank({ ...bank, sort_code: e.target.value })}
        />
        <TextField
          label={t("pay.accountNumber")}
          inputMode="numeric"
          value={bank.account_number}
          onChange={(e) => setBank({ ...bank, account_number: e.target.value })}
        />
        <Button type="submit" size="sm" disabled={saveBank.isPending}>
          {t("pay.saveBank")}
        </Button>
        {saveBank.error ? <Alert tone="danger">{saveBank.error.message}</Alert> : null}
      </form>
      {p.employment_type === "self_employed" ? (
        p.self_billing_agreed_at ? (
          <p className="text-sm">{t("pay.selfBillingAgreed")}</p>
        ) : (
          <div className="space-y-2 text-sm">
            <p>{t("pay.selfBillingText")}</p>
            <Button size="sm" variant="secondary" onClick={() => agree.mutate()}>
              {t("pay.agreeSelfBilling")}
            </Button>
          </div>
        )
      ) : null}
      {p.method === "stripe_connect" && !p.stripe_payouts_enabled ? (
        <Button size="sm" variant="secondary" onClick={() => stripe.mutate()}>
          {t("pay.setUpStripe")}
        </Button>
      ) : null}
    </section>
  );
}
