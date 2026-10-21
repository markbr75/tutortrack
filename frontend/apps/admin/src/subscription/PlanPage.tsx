import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PageHeader,
  PanelFooter,
  RuledPanel,
  SelectField,
  Spinner,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import { AddonsSection } from "./AddonsSection";
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

  if (subscription.isPending) return <Spinner label={t("grid.loading")} />;
  if (!subscription.data) return <Alert tone="info">{t("plan.noSubscription")}</Alert>;
  const sub = subscription.data;
  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader title={t("plan.title")} />
      {returned.isSuccess ? <Alert tone="success">{t("plan.thanks")}</Alert> : null}
      <StatusSection sub={sub} />
      {usage.data ? <UsageSection usage={usage.data} /> : null}
      <PlansSection sub={sub} />
      {usage.data ? (
        <CreditsSection credits={usage.data.credits} canManage={sub.can_manage} />
      ) : null}
      <AddonsSection canManage={sub.can_manage} />
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
  const actions = sub.can_manage
    ? [
        !sub.has_payment_method && !locked ? (
          <Button key="card" onClick={() => checkout.mutate()} loading={checkout.isPending}>
            {t("plan.addCard")}
          </Button>
        ) : null,
        locked ? (
          <Button
            key="reactivate"
            onClick={() => reactivate.mutate()}
            loading={reactivate.isPending}
          >
            {t("plan.reactivate")}
          </Button>
        ) : null,
        sub.has_payment_method ? (
          <Button
            key="portal"
            variant="secondary"
            onClick={() => portal.mutate()}
            loading={portal.isPending}
          >
            {t("plan.managePayment")}
          </Button>
        ) : null,
      ].filter(Boolean)
    : [];
  return (
    <RuledPanel
      titleId="plan-status"
      title={t("plan.current", { plan: sub.plan_name })}
      aside={
        <span className={sub.status === "past_due" ? "font-semibold text-margin" : "font-medium"}>
          {t(`plan.status.${sub.status}`)}
        </span>
      }
      footer={actions.length ? actions : undefined}
      bodyClassName="space-y-3 text-sm"
    >
      {sub.status === "trialing" ? (
        <p className="tabular-nums">
          {t("plan.trialLeft", { count: trialDays })}{" "}
          {sub.has_payment_method
            ? t("plan.trialThen", { plan: sub.plan_name })
            : t("plan.trialNoCard")}
        </p>
      ) : null}
      {sub.status === "past_due" ? <Alert tone="warning">{t("plan.pastDue")}</Alert> : null}
      {locked ? <Alert tone="warning">{t("plan.locked")}</Alert> : null}
      {sub.current_period_end && sub.status === "active" ? (
        <p className="tabular-nums">
          {sub.cancel_at_period_end
            ? t("plan.endsOn", { date: formatDate(sub.current_period_end) })
            : t("plan.renewsOn", { date: formatDate(sub.current_period_end) })}
        </p>
      ) : null}
      {sub.pending_plan ? (
        <p>{t("plan.pendingChange", { plan: t(`plan.names.${sub.pending_plan}`) })}</p>
      ) : null}
      {sub.card ? (
        <p className="text-muted-foreground tabular-nums">
          {t("plan.card", { brand: sub.card.brand, last4: sub.card.last4 })}
        </p>
      ) : null}
      {[checkout.error, portal.error, reactivate.error].map((e, i) =>
        e ? (
          <Alert key={i} tone="danger">
            {e.message}
          </Alert>
        ) : null,
      )}
    </RuledPanel>
  );
}

function UsageSection({ usage }: { usage: Usage }) {
  const { t } = useTranslation();
  return (
    <RuledPanel
      flush
      titleId="plan-usage"
      title={t("plan.usage")}
      footer={
        <p className="tabular-nums">
          {t("plan.seats", { billable: usage.billable_tutors, included: usage.included_tutors })}
          {usage.next_invoice
            ? ` ${t("plan.nextInvoice", { amount: formatMoney(usage.next_invoice) })}`
            : ""}
        </p>
      }
    >
      <ul className="text-sm">
        {usage.limits.map((limit) => (
          <li
            key={limit.key}
            className="flex justify-between gap-4 border-t border-rule px-5 py-2.5 first:border-0"
          >
            <span>{limit.title}</span>
            <span
              className={
                limit.allowed !== null && limit.used >= limit.allowed
                  ? "font-semibold tabular-nums"
                  : "tabular-nums"
              }
            >
              {limit.allowed === null
                ? t("plan.usedUnlimited", { used: limit.used })
                : t("plan.usedOf", { used: limit.used, allowed: limit.allowed })}
            </span>
          </li>
        ))}
      </ul>
    </RuledPanel>
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
    <div className="space-y-4">
      <RuledPanel
        flush
        titleId="plan-choose"
        title={t("plan.plans")}
        aside={
          <fieldset className="flex gap-4">
            <legend className="sr-only">{t("plan.billing")}</legend>
            {(["month", "year"] as const).map((value) => (
              <label key={value} className="flex items-center gap-1.5">
                <input
                  type="radio"
                  className="size-4"
                  name="interval"
                  value={value}
                  checked={interval === value}
                  onChange={() => setInterval(value)}
                />
                {t(`plan.interval.${value}`)}
              </label>
            ))}
          </fieldset>
        }
      >
        {plans.isPending ? (
          <div className="px-5 py-4">
            <Spinner label={t("grid.loading")} />
          </div>
        ) : null}
        <ul className="text-sm">
          {plans.data?.map((plan) => {
            const lines = priceLines(t, plan, interval);
            const isCurrent = plan.key === sub.plan && interval === sub.interval;
            return (
              <li
                key={plan.key}
                className="grid gap-x-6 gap-y-2 border-t border-rule px-5 py-3.5 first:border-0 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_10rem] sm:items-start"
              >
                <div className="min-w-0">
                  <h3 className="font-semibold">{plan.name}</h3>
                  <p className="text-xs text-muted-foreground">{plan.description}</p>
                </div>
                <ul className="tabular-nums">
                  {lines.length ? (
                    lines.map((line) => <li key={line}>{line}</li>)
                  ) : (
                    <li>{t("plan.contactSales")}</li>
                  )}
                  {plan.limits.max_tutors !== null && plan.limits.max_tutors !== undefined ? (
                    <li className="text-muted-foreground">
                      {t("plan.upToTutors", { count: plan.limits.max_tutors })}
                    </li>
                  ) : (
                    <li className="text-muted-foreground">{t("plan.unlimitedTutors")}</li>
                  )}
                </ul>
                <div className="sm:text-right">
                  {isCurrent ? (
                    <span className="font-semibold">{t("plan.yourPlan")}</span>
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
      </RuledPanel>
      {choice ? (
        <div
          role="region"
          aria-label={t("plan.confirmTitle")}
          className="rounded-xl border border-border bg-surface"
        >
          <div className="space-y-2 px-5 py-4">
            <h3 className="text-base font-semibold">
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
              <p className="text-sm tabular-nums">
                {t(`plan.effective.${choice.preview.effective}`)}
                {choice.preview.amount_due_now
                  ? ` ${t("plan.dueNow", { amount: formatMoney(choice.preview.amount_due_now) })}`
                  : ""}
              </p>
            )}
          </div>
          <PanelFooter>
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
          </PanelFooter>
        </div>
      ) : null}
      {[preview.error, change.error, checkout.error].map((e, i) =>
        e ? (
          <Alert key={i} tone="danger">
            {e.message}
          </Alert>
        ) : null,
      )}
    </div>
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
    <RuledPanel flush titleId="plan-credits" title={t("plan.credits")}>
      <ul className="text-sm">
        {credits.map((acct) => {
          const kind = acct.credit_type;
          return (
            <li key={kind} className="space-y-2 border-t border-rule px-5 py-3.5 first:border-0">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h3 className="font-semibold">{t(`plan.creditTypes.${kind}`)}</h3>
                <p className="tabular-nums">
                  {t("plan.creditBalance", {
                    balance: acct.balance,
                    used: acct.used_this_period,
                    allowance: acct.allowance,
                  })}
                </p>
              </div>
              {canManage ? (
                <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
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
                        className="size-4"
                        checked={acct[field]}
                        onChange={(e) =>
                          settings.mutate({ kind, body: { [field]: e.target.checked } })
                        }
                      />
                      {t(`plan.${field}`)}
                    </label>
                  ))}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      {topUp.error ? (
        <div className="px-5 pb-4">
          <Alert tone="danger">{topUp.error.message}</Alert>
        </div>
      ) : null}
    </RuledPanel>
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
    <RuledPanel flush titleId="plan-invoices" title={t("plan.invoices")}>
      <div
        role="region"
        aria-labelledby="plan-invoices"
        tabIndex={0}
        className="relative overflow-x-auto"
      >
        <table className="w-full min-w-[32rem] text-sm">
          <thead className="border-b border-border">
            <tr>
              <th scope="col" className="py-2.5 pr-4 pl-5">
                {t("plan.invoiceNumber")}
              </th>
              <th scope="col" className="px-4 py-2.5">
                {t("plan.invoiceDate")}
              </th>
              <th scope="col" className="w-32 px-4 py-2.5 text-right">
                {t("plan.invoiceTotal")}
              </th>
              <th scope="col" className="px-4 py-2.5">
                {t("plan.invoiceStatus")}
              </th>
              <th scope="col" className="py-2.5 pr-5 pl-4">
                <span className="sr-only">PDF</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {invoices.data.map((inv) => (
              <tr key={inv.id}>
                <td className="py-2.5 pr-4 pl-5 font-medium">{inv.number}</td>
                <td className="px-4 py-2.5 whitespace-nowrap">{formatDate(inv.created)}</td>
                <td className="px-4 py-2.5 text-right whitespace-nowrap">
                  {formatMoney(inv.total)}
                </td>
                <td className="px-4 py-2.5">{inv.status}</td>
                <td className="py-2.5 pr-5 pl-4 text-right">
                  {inv.pdf_url ? (
                    <a
                      className="font-medium text-link underline-offset-2 hover:underline"
                      href={inv.pdf_url}
                    >
                      {t("plan.download", { number: inv.number })}
                    </a>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </RuledPanel>
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
      <RuledPanel
        footer={
          <Button variant="secondary" onClick={() => undo.mutate()} loading={undo.isPending}>
            {t("plan.keepSubscription")}
          </Button>
        }
      >
        <p className="text-sm">{t("plan.cancelScheduled")}</p>
      </RuledPanel>
    );
  }
  return (
    <RuledPanel titleId="plan-cancel" title={t("plan.cancelTitle")}>
      {!open ? (
        <Button
          variant="ghost"
          className="-ml-4 text-muted-foreground"
          onClick={() => setOpen(true)}
        >
          {t("plan.cancel")}
        </Button>
      ) : (
        <form
          className="max-w-md space-y-4"
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
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">{t("plan.cancelFeedback")}</span>
            <textarea
              className="w-full rounded-md border bg-surface px-3 py-2 text-sm"
              rows={3}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
            />
          </label>
          <div className="flex flex-wrap gap-2">
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
    </RuledPanel>
  );
}
