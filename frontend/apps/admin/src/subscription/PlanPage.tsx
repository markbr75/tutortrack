import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import {
  daysUntil,
  useSubscription,
  type ChangePreview,
  type CreditAccount,
  type Plan,
  type Subscription,
  type Usage,
} from "./hooks";

type Interval = "month" | "year";

function useRefresh() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of [
      "subscription",
      "subscription-usage",
      "entitlements",
      "me",
      "organisation",
    ]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  };
}

function go(url: string) {
  if (url) window.location.assign(url);
}

/** Back from Stripe Checkout (`?checkout=<session>`): record it straight away. */
function useCheckoutReturn() {
  const refresh = useRefresh();
  const done = useRef(false);
  const complete = useMutation({
    mutationFn: async (session_id: string) =>
      unwrap(
        await api.POST("/api/v1/subscription/checkout-session/complete", { body: { session_id } }),
      ),
    onSettled: refresh,
  });
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const session = params.get("checkout");
    if (!session || done.current) return;
    done.current = true;
    params.delete("checkout");
    const query = params.toString();
    window.history.replaceState(null, "", window.location.pathname + (query ? `?${query}` : ""));
    complete.mutate(session);
  }, [complete]);
  return complete;
}

/** Settings → Billing & plan (FR-04-7, FR-04-5, FR-04-8). */
export function PlanPage() {
  const { t } = useTranslation();
  const subscription = useSubscription();
  const returned = useCheckoutReturn();
  const usage = useQuery({
    queryKey: ["subscription-usage"],
    queryFn: async () => unwrap(await api.GET("/api/v1/subscription/usage")),
    enabled: subscription.isSuccess,
  });

  if (subscription.isPending) return <Spinner className="size-5" label={t("grid.loading")} />;
  if (!subscription.data) return <Alert tone="info">{t("plan.noSubscription")}</Alert>;
  const sub = subscription.data;
  return (
    <div className="max-w-4xl space-y-8">
      <h1 className="text-2xl font-semibold">{t("plan.title")}</h1>
      {returned.isSuccess ? <Alert tone="success">{t("plan.thanks")}</Alert> : null}
      <StatusSection sub={sub} />
      {usage.data ? <UsageSection usage={usage.data} /> : null}
      <PlansSection sub={sub} />
      {usage.data ? (
        <CreditsSection credits={usage.data.credits} canManage={sub.can_manage} />
      ) : null}
      <InvoicesSection />
      {sub.can_manage ? <CancelSection sub={sub} /> : null}
    </div>
  );
}

function StatusSection({ sub }: { sub: Subscription }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const checkout = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/subscription/checkout-session", {
          body: { plan: sub.plan, interval: sub.interval },
        }),
      ),
    onSuccess: (r) => go(r.url),
  });
  const portal = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/subscription/portal-session")),
    onSuccess: (r) => go(r.url),
  });
  const reactivate = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/subscription/reactivate")),
    onSuccess: (r) => (r.url ? go(r.url) : refresh()),
  });
  const trialDays = daysUntil(sub.trial_ends_at);
  const locked = sub.status === "suspended" || sub.status === "cancelled";
  return (
    <section
      aria-labelledby="plan-status"
      className="space-y-3 rounded-md border border-border p-4"
    >
      <h2 id="plan-status" className="text-lg font-semibold">
        {t("plan.current", { plan: sub.plan_name })}{" "}
        <span className="ml-1 rounded bg-muted px-2 py-0.5 text-xs font-medium">
          {t(`plan.status.${sub.status}`)}
        </span>
      </h2>
      {sub.status === "trialing" ? (
        <p className="text-sm">
          {t("plan.trialLeft", { count: trialDays })}{" "}
          {sub.has_payment_method
            ? t("plan.trialThen", { plan: sub.plan_name })
            : t("plan.trialNoCard")}
        </p>
      ) : null}
      {sub.status === "past_due" ? <Alert tone="warning">{t("plan.pastDue")}</Alert> : null}
      {locked ? <Alert tone="warning">{t("plan.locked")}</Alert> : null}
      {sub.current_period_end && sub.status === "active" ? (
        <p className="text-sm">
          {sub.cancel_at_period_end
            ? t("plan.endsOn", { date: formatDate(sub.current_period_end) })
            : t("plan.renewsOn", { date: formatDate(sub.current_period_end) })}
        </p>
      ) : null}
      {sub.pending_plan ? (
        <p className="text-sm">
          {t("plan.pendingChange", { plan: t(`plan.names.${sub.pending_plan}`) })}
        </p>
      ) : null}
      {sub.card ? (
        <p className="text-sm text-muted-foreground">
          {t("plan.card", { brand: sub.card.brand, last4: sub.card.last4 })}
        </p>
      ) : null}
      {sub.can_manage ? (
        <div className="flex flex-wrap gap-2">
          {!sub.has_payment_method && !locked ? (
            <Button onClick={() => checkout.mutate()} loading={checkout.isPending}>
              {t("plan.addCard")}
            </Button>
          ) : null}
          {locked ? (
            <Button onClick={() => reactivate.mutate()} loading={reactivate.isPending}>
              {t("plan.reactivate")}
            </Button>
          ) : null}
          {sub.has_payment_method ? (
            <Button variant="secondary" onClick={() => portal.mutate()} loading={portal.isPending}>
              {t("plan.managePayment")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {[checkout.error, portal.error, reactivate.error].map((e, i) =>
        e ? (
          <Alert key={i} tone="danger">
            {e.message}
          </Alert>
        ) : null,
      )}
    </section>
  );
}

function UsageSection({ usage }: { usage: Usage }) {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="plan-usage" className="space-y-3">
      <h2 id="plan-usage" className="text-lg font-semibold">
        {t("plan.usage")}
      </h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {usage.limits.map((limit) => (
          <li key={limit.key} className="rounded-md border border-border p-3 text-sm">
            <div className="flex justify-between">
              <span>{limit.title}</span>
              <span>
                {limit.allowed === null
                  ? t("plan.usedUnlimited", { used: limit.used })
                  : t("plan.usedOf", { used: limit.used, allowed: limit.allowed })}
              </span>
            </div>
            {limit.allowed !== null ? (
              <progress
                className="mt-2 h-2 w-full"
                max={Math.max(limit.allowed, 1)}
                value={Math.min(limit.used, limit.allowed)}
                aria-label={limit.title}
              />
            ) : null}
          </li>
        ))}
      </ul>
      <p className="text-sm">
        {t("plan.seats", { billable: usage.billable_tutors, included: usage.included_tutors })}
        {usage.next_invoice
          ? ` ${t("plan.nextInvoice", { amount: formatMoney(usage.next_invoice) })}`
          : ""}
      </p>
    </section>
  );
}

function priceLines(
  t: (k: string, o?: Record<string, unknown>) => string,
  plan: Plan,
  interval: Interval,
) {
  const money = (amount: string) => formatMoney({ amount, currency: plan.currency });
  return plan.prices
    .filter((p) => p.interval === interval)
    .map((p) => {
      if (p.component === "revenue_share")
        return t("plan.price.revenue_share", { percent: p.unit_amount });
      return t(`plan.price.${p.component}.${interval}`, {
        amount: money(p.unit_amount),
        included: p.included_quantity,
      });
    });
}

function PlansSection({ sub }: { sub: Subscription }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const [interval, setInterval] = useState<Interval>(sub.interval);
  const [choice, setChoice] = useState<{ plan: string; preview: ChangePreview } | null>(null);
  const plans = useQuery({
    queryKey: ["subscription-plans"],
    queryFn: async () => unwrap(await api.GET("/api/v1/subscription/plans")),
  });
  const preview = useMutation({
    mutationFn: async (plan: string) =>
      unwrap(
        await api.POST("/api/v1/subscription/change-plan", {
          params: { query: { preview: true } },
          body: { plan, interval },
        }),
      ) as unknown as ChangePreview,
    onSuccess: (result, plan) => setChoice({ plan, preview: result }),
  });
  const change = useMutation({
    mutationFn: async (plan: string) =>
      unwrap(await api.POST("/api/v1/subscription/change-plan", { body: { plan, interval } })),
    onSuccess: () => {
      setChoice(null);
      refresh();
    },
  });
  const checkout = useMutation({
    mutationFn: async (plan: string) =>
      unwrap(await api.POST("/api/v1/subscription/checkout-session", { body: { plan, interval } })),
    onSuccess: (r) => go(r.url),
  });
  const confirm = (plan: string, p: ChangePreview) =>
    p.effective === "checkout" ? checkout.mutate(plan) : change.mutate(plan);

  return (
    <section aria-labelledby="plan-choose" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="plan-choose" className="text-lg font-semibold">
          {t("plan.plans")}
        </h2>
        <fieldset className="flex gap-3 text-sm">
          <legend className="sr-only">{t("plan.billing")}</legend>
          {(["month", "year"] as const).map((value) => (
            <label key={value} className="flex items-center gap-1">
              <input
                type="radio"
                name="interval"
                value={value}
                checked={interval === value}
                onChange={() => setInterval(value)}
              />
              {t(`plan.interval.${value}`)}
            </label>
          ))}
        </fieldset>
      </div>
      {plans.isPending ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      <ul className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {plans.data?.map((plan) => {
          const lines = priceLines(t, plan, interval);
          const isCurrent = plan.key === sub.plan && interval === sub.interval;
          return (
            <li key={plan.key} className="flex flex-col rounded-md border border-border p-4">
              <h3 className="font-semibold">{plan.name}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{plan.description}</p>
              <ul className="mt-2 text-sm">
                {lines.length ? (
                  lines.map((line) => <li key={line}>{line}</li>)
                ) : (
                  <li>{t("plan.contactSales")}</li>
                )}
                {plan.limits.max_tutors !== null && plan.limits.max_tutors !== undefined ? (
                  <li>{t("plan.upToTutors", { count: plan.limits.max_tutors })}</li>
                ) : (
                  <li>{t("plan.unlimitedTutors")}</li>
                )}
              </ul>
              <div className="mt-auto pt-3">
                {isCurrent ? (
                  <span className="text-sm font-medium">{t("plan.yourPlan")}</span>
                ) : sub.can_manage && plan.visibility === "public" && lines.length ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => preview.mutate(plan.key)}
                    loading={preview.isPending && preview.variables === plan.key}
                  >
                    {t("plan.choose", { plan: plan.name })}
                  </Button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
      {choice ? (
        <div
          role="region"
          aria-label={t("plan.confirmTitle")}
          className="space-y-2 rounded-md border border-border p-4"
        >
          <h3 className="font-semibold">
            {t("plan.confirmTitle")}: {t(`plan.names.${choice.plan}`)}
          </h3>
          {choice.preview.blockers.length ? (
            <Alert tone="warning" title={t("plan.blockersTitle")}>
              <ul className="list-disc pl-5">
                {choice.preview.blockers.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </Alert>
          ) : (
            <p className="text-sm">
              {t(`plan.effective.${choice.preview.effective}`)}
              {choice.preview.amount_due_now
                ? ` ${t("plan.dueNow", { amount: formatMoney(choice.preview.amount_due_now) })}`
                : ""}
            </p>
          )}
          <div className="flex gap-2">
            {!choice.preview.blockers.length ? (
              <Button
                onClick={() => confirm(choice.plan, choice.preview)}
                loading={change.isPending || checkout.isPending}
              >
                {t("plan.confirm")}
              </Button>
            ) : null}
            <Button variant="ghost" onClick={() => setChoice(null)}>
              {t("common.cancel")}
            </Button>
          </div>
        </div>
      ) : null}
      {[preview.error, change.error, checkout.error].map((e, i) =>
        e ? (
          <Alert key={i} tone="danger">
            {e.message}
          </Alert>
        ) : null,
      )}
    </section>
  );
}

function CreditsSection({ credits, canManage }: { credits: CreditAccount[]; canManage: boolean }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const topUp = useMutation({
    mutationFn: async ({ kind, count }: { kind: "sms" | "ai"; count: number }) =>
      unwrap(
        await api.POST("/api/v1/subscription/credits/{credit_type}/top-up", {
          params: { path: { credit_type: kind } },
          body: { credits: count },
        }),
      ),
    onSuccess: (r) => (r.status === "redirect" ? go(r.url) : refresh()),
  });
  const settings = useMutation({
    mutationFn: async ({ kind, body }: { kind: "sms" | "ai"; body: Record<string, boolean> }) =>
      unwrap(
        await api.PATCH("/api/v1/subscription/credits/{credit_type}", {
          params: { path: { credit_type: kind } },
          body,
        }),
      ),
    onSuccess: refresh,
  });
  return (
    <section aria-labelledby="plan-credits" className="space-y-3">
      <h2 id="plan-credits" className="text-lg font-semibold">
        {t("plan.credits")}
      </h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {credits.map((acct) => {
          const kind = acct.credit_type;
          return (
            <li key={kind} className="space-y-2 rounded-md border border-border p-3 text-sm">
              <h3 className="font-medium">{t(`plan.creditTypes.${kind}`)}</h3>
              <p>
                {t("plan.creditBalance", {
                  balance: acct.balance,
                  used: acct.used_this_period,
                  allowance: acct.allowance,
                })}
              </p>
              {canManage ? (
                <>
                  <div className="flex flex-wrap gap-2">
                    {acct.packs.map((count) => (
                      <Button
                        key={count}
                        size="sm"
                        variant="secondary"
                        onClick={() => topUp.mutate({ kind, count })}
                        loading={topUp.isPending && topUp.variables?.count === count}
                      >
                        {t("plan.buy", { count })}
                      </Button>
                    ))}
                  </div>
                  {(["auto_top_up", "allow_overage"] as const).map((field) => (
                    <label key={field} className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={acct[field]}
                        onChange={(e) =>
                          settings.mutate({ kind, body: { [field]: e.target.checked } })
                        }
                      />
                      {t(`plan.${field}`)}
                    </label>
                  ))}
                </>
              ) : null}
            </li>
          );
        })}
      </ul>
      {topUp.error ? <Alert tone="danger">{topUp.error.message}</Alert> : null}
    </section>
  );
}

function InvoicesSection() {
  const { t } = useTranslation();
  const invoices = useQuery({
    queryKey: ["subscription-invoices"],
    queryFn: async () => unwrap(await api.GET("/api/v1/subscription/invoices")),
  });
  if (!invoices.data?.length) return null;
  return (
    <section aria-labelledby="plan-invoices" className="space-y-2">
      <h2 id="plan-invoices" className="text-lg font-semibold">
        {t("plan.invoices")}
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th scope="col">{t("plan.invoiceNumber")}</th>
              <th scope="col">{t("plan.invoiceDate")}</th>
              <th scope="col">{t("plan.invoiceTotal")}</th>
              <th scope="col">{t("plan.invoiceStatus")}</th>
              <th scope="col">
                <span className="sr-only">PDF</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {invoices.data.map((inv) => (
              <tr key={inv.id} className="border-t border-border">
                <td>{inv.number}</td>
                <td>{formatDate(inv.created)}</td>
                <td>{formatMoney(inv.total)}</td>
                <td>{inv.status}</td>
                <td>
                  {inv.pdf_url ? (
                    <a className="underline" href={inv.pdf_url}>
                      {t("plan.download", { number: inv.number })}
                    </a>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const REASONS = ["too_expensive", "missing_features", "switching", "closing", "other"] as const;

function CancelSection({ sub }: { sub: Subscription }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<(typeof REASONS)[number]>("too_expensive");
  const [feedback, setFeedback] = useState("");
  const cancel = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/subscription/cancel", { body: { reason, feedback } })),
    onSuccess: () => {
      setOpen(false);
      refresh();
    },
  });
  const undo = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/subscription/reactivate")),
    onSuccess: (r) => (r.url ? go(r.url) : refresh()),
  });
  if (sub.status === "cancelled" || sub.status === "suspended") return null;
  if (sub.cancel_at_period_end) {
    return (
      <section className="space-y-2">
        <p className="text-sm">{t("plan.cancelScheduled")}</p>
        <Button variant="secondary" onClick={() => undo.mutate()} loading={undo.isPending}>
          {t("plan.keepSubscription")}
        </Button>
      </section>
    );
  }
  return (
    <section aria-labelledby="plan-cancel" className="space-y-2">
      <h2 id="plan-cancel" className="text-lg font-semibold">
        {t("plan.cancelTitle")}
      </h2>
      {!open ? (
        <Button variant="ghost" onClick={() => setOpen(true)}>
          {t("plan.cancel")}
        </Button>
      ) : (
        <form
          className="max-w-md space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            cancel.mutate();
          }}
        >
          <p className="text-sm">{t("plan.cancelHelp")}</p>
          <SelectField
            label={t("plan.cancelReason")}
            value={reason}
            options={REASONS.map((r) => ({ value: r, label: t(`plan.reasons.${r}`) }))}
            onChange={(e) => setReason(e.target.value as (typeof REASONS)[number])}
          />
          <label className="block text-sm">
            <span className="font-medium">{t("plan.cancelFeedback")}</span>
            <textarea
              className="mt-1 w-full rounded-md border border-border p-2"
              rows={3}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
            />
          </label>
          <div className="flex gap-2">
            <Button type="submit" variant="danger" loading={cancel.isPending}>
              {t("plan.confirmCancel")}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("plan.keepSubscription")}
            </Button>
          </div>
          {cancel.error ? <Alert tone="danger">{cancel.error.message}</Alert> : null}
        </form>
      )}
    </section>
  );
}
