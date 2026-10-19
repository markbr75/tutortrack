import { unwrap } from "@tutortrack/api-client";
import { formatMoney, useTranslation } from "@tutortrack/i18n";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { api, useOrganisation, usePermission } from "../api";
import { subtractAmounts } from "./data";

type WidgetValue = { label: string; currency: string; value: string; previous: string | null };

function useWidgetValues(key: string, enabled: boolean) {
  const query = useQuery({
    queryKey: ["home-widget", key],
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/reporting/widgets/{key}", {
          params: { path: { key }, query: { period: "this_month", compare: "previous_period" } },
        }),
      ),
  });
  return { pending: query.isPending, values: (query.data?.values ?? []) as WidgetValue[] };
}

function Figure({
  label,
  to,
  pending,
  children,
}: {
  label: string;
  to: string;
  pending: boolean;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0 py-4 max-md:border-t max-md:border-rule max-md:first:border-0 md:border-l md:border-rule md:px-5 md:first:border-0 md:first:pl-0">
      <Link to={to} className="text-sm text-muted-foreground hover:text-foreground hover:underline">
        {label}
      </Link>
      {pending ? (
        <div aria-hidden="true" className="mt-2 h-7 w-32 animate-pulse rounded bg-muted" />
      ) : (
        children
      )}
    </div>
  );
}

function Amount({ children }: { children: ReactNode }) {
  return <p className="mt-1 text-xl font-semibold tabular-nums">{children}</p>;
}

/** One ruled line of money: what came in this month, what is owed, what tutors are due. */
export function MoneyStrip() {
  const { t, i18n } = useTranslation();
  const { data: org } = useOrganisation();
  const finance = usePermission("reporting.finance.view");
  const payroll = usePermission("reporting.payroll.view");
  const revenue = useWidgetValues("revenue", finance);
  const outstanding = useWidgetValues("outstanding", finance);
  const payRun = useWidgetValues("next_pay_run", payroll);
  if (!finance && !payroll) return null;
  const currency = org?.default_currency;
  if (!currency) {
    // Amounts are formatted in the organisation's currency, so wait for it.
    return (
      <div aria-hidden="true" className="grid border-y border-border py-4 md:grid-cols-3">
        <div className="h-12 w-40 animate-pulse rounded bg-muted" />
      </div>
    );
  }
  const money = (amount: string, code: string) =>
    formatMoney({ amount, currency: code }, i18n.language);
  // The outstanding widget sends, per currency, the amount owed then the part that is overdue.
  const owed: { currency: string; total: string; overdue: string }[] = [];
  for (let i = 0; i + 1 < outstanding.values.length; i += 2) {
    const [total, overdue] = [outstanding.values[i]!, outstanding.values[i + 1]!];
    owed.push({ currency: total.currency, total: total.value, overdue: overdue.value });
  }

  return (
    <section
      aria-label={t("home.money.title")}
      className="grid border-y border-border md:grid-cols-3"
    >
      {finance ? (
        <Figure label={t("home.money.revenue")} to="/analytics" pending={revenue.pending}>
          {revenue.values.length === 0 ? (
            <>
              <Amount>{money("0", currency)}</Amount>
              <p className="text-sm text-muted-foreground">{t("home.money.revenueNone")}</p>
            </>
          ) : (
            revenue.values.map((v) => {
              const diff = v.previous == null ? null : subtractAmounts(v.value, v.previous);
              const up = diff != null && !diff.startsWith("-") && /[1-9]/.test(diff);
              const change =
                diff == null
                  ? null
                  : !/[1-9]/.test(diff)
                    ? t("home.money.revenueSame")
                    : t(up ? "home.money.revenueUp" : "home.money.revenueDown", {
                        amount: money(diff.replace("-", ""), v.currency),
                      });
              return (
                <div key={v.currency}>
                  <Amount>{money(v.value, v.currency)}</Amount>
                  {change ? (
                    <p className={up ? "text-sm text-success" : "text-sm text-muted-foreground"}>
                      {change}
                    </p>
                  ) : null}
                </div>
              );
            })
          )}
        </Figure>
      ) : null}
      {finance ? (
        <Figure label={t("home.money.outstanding")} to="/billing" pending={outstanding.pending}>
          {owed.length === 0 ? (
            <>
              <Amount>{money("0", currency)}</Amount>
              <p className="text-sm text-muted-foreground">{t("home.money.noneOverdue")}</p>
            </>
          ) : (
            owed.map((o) => (
              <div key={o.currency}>
                <Amount>{money(o.total, o.currency)}</Amount>
                {/[1-9]/.test(o.overdue) && !o.overdue.startsWith("-") ? (
                  <p className="text-sm font-medium text-margin">
                    {t("home.money.overdue", { amount: money(o.overdue, o.currency) })}
                  </p>
                ) : (
                  <p className="text-sm text-muted-foreground">{t("home.money.noneOverdue")}</p>
                )}
              </div>
            ))
          )}
        </Figure>
      ) : null}
      {payroll ? (
        <Figure label={t("home.money.payRun")} to="/payroll" pending={payRun.pending}>
          {payRun.values.length === 0 ? (
            <>
              <Amount>{money("0", currency)}</Amount>
              <p className="text-sm text-muted-foreground">{t("home.money.payRunNone")}</p>
            </>
          ) : (
            payRun.values.map((v) => (
              <div key={v.currency}>
                <Amount>{money(v.value, v.currency)}</Amount>
                <p className="text-sm text-muted-foreground">{t("home.money.payRunReady")}</p>
              </div>
            ))
          )}
        </Figure>
      ) : null}
    </section>
  );
}
