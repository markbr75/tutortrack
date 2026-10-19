import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { RegisterMark } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { api, usePermission } from "../api";

const SHOWN = 5;

function Panel({
  id,
  title,
  aside,
  pending,
  empty,
  more,
  rule = "border-border",
  children,
}: {
  rule?: string;
  id: string;
  title: string;
  aside?: ReactNode;
  pending: boolean;
  empty: string | null;
  more: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="rounded-xl border border-border bg-surface">
      <div className={`flex items-baseline justify-between gap-3 border-b px-5 py-3.5 ${rule}`}>
        <h2 id={id} className="text-base font-semibold">
          {title}
        </h2>
        {aside}
      </div>
      {pending ? (
        <div aria-hidden="true" className="space-y-3 p-5">
          <div className="h-8 animate-pulse rounded bg-muted" />
          <div className="h-8 animate-pulse rounded bg-muted" />
        </div>
      ) : empty ? (
        <p className="px-5 py-6 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <>
          <ul>{children}</ul>
          <div className="border-t border-rule px-5 py-3 text-sm">{more}</div>
        </>
      )}
    </section>
  );
}

function daysSince(iso: string, now: Date): number {
  return Math.max(1, Math.floor((now.getTime() - new Date(iso).getTime()) / 86_400_000));
}

/** Past lessons nobody has marked, oldest first (FR-09-8). */
export function NeedsMarking({ now = new Date() }: { now?: Date }) {
  const { t, i18n } = useTranslation();
  const query = useQuery({
    queryKey: ["home-unconfirmed"],
    queryFn: async () => unwrap(await api.GET("/api/v1/unconfirmed-lessons")),
  });
  const lessons = query.data ?? [];
  return (
    <Panel
      id="needs-marking-h"
      title={t("home.needsMarking.title")}
      rule="border-margin"
      aside={
        lessons.length ? (
          <span className="text-sm font-semibold text-margin">
            {t("home.needsMarking.count", { count: lessons.length })}
          </span>
        ) : null
      }
      pending={query.isPending}
      empty={lessons.length ? null : t("home.needsMarking.empty")}
      more={
        <Link to="/unconfirmed" className="font-medium text-link hover:underline">
          {t("home.needsMarking.open")}
        </Link>
      }
    >
      {lessons.slice(0, SHOWN).map((lesson) => (
        <li key={lesson.id} className="border-t border-rule first:border-0">
          <Link
            to="/unconfirmed"
            className="flex items-start gap-3 px-5 py-2.5 text-sm hover:bg-muted"
          >
            <RegisterMark kind="due" label={t("home.register.marks.due")} className="mt-px" />
            <span className="min-w-0 flex-1">
              <span className="block">{lesson.title}</span>
              <span className="block text-xs text-muted-foreground">
                {[
                  formatDate(lesson.start, i18n.language),
                  lesson.tutors.map((tutor) => tutor.name).join(", "),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </span>
            <span className="shrink-0 text-xs font-semibold text-margin">
              {t("home.needsMarking.days", { count: daysSince(lesson.end, now) })}
            </span>
          </Link>
        </li>
      ))}
    </Panel>
  );
}

/** Invoices past their due date with money still owed, oldest due first. */
export function OverdueInvoices() {
  const { t, i18n } = useTranslation();
  const query = useQuery({
    queryKey: ["home-overdue"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/invoices", {
          params: { query: { overdue: true, ordering: "due_date", page_size: SHOWN } },
        }),
      ).results,
  });
  const invoices = query.data ?? [];
  // The total owed comes from the outstanding figure (finance roles only), not the five rows.
  const finance = usePermission("reporting.finance.view");
  const outstanding = useQuery({
    queryKey: ["home-widget", "outstanding"],
    enabled: finance,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/reporting/widgets/{key}", {
          params: {
            path: { key: "outstanding" },
            query: { period: "this_month", compare: "previous_period" },
          },
        }),
      ),
  });
  const overdue = (outstanding.data?.values ?? []).filter((_, index) => index % 2 === 1);
  const total =
    overdue.length === 1 && /[1-9]/.test(String(overdue[0]!.value))
      ? formatMoney(
          { amount: String(overdue[0]!.value), currency: overdue[0]!.currency },
          i18n.language,
        )
      : null;
  return (
    <Panel
      id="overdue-h"
      title={t("home.overdue.title")}
      aside={total ? <span className="text-sm font-semibold tabular-nums">{total}</span> : null}
      pending={query.isPending}
      empty={invoices.length ? null : t("home.overdue.empty")}
      more={
        <Link to="/billing" className="font-medium text-link hover:underline">
          {t("home.overdue.open")}
        </Link>
      }
    >
      {invoices.map((invoice) => (
        <li key={invoice.id} className="border-t border-rule first:border-0">
          <Link
            to="/invoices/$invoiceId"
            params={{ invoiceId: invoice.id }}
            className="flex items-start justify-between gap-3 px-5 py-2.5 text-sm hover:bg-muted"
          >
            <span className="min-w-0">
              <span className="block truncate">{invoice.client_name}</span>
              <span className="block text-xs text-muted-foreground">
                {t("home.overdue.due", {
                  number: invoice.number,
                  date: invoice.due_date ? formatDate(invoice.due_date, i18n.language) : "",
                })}
              </span>
            </span>
            <span className="shrink-0 font-semibold tabular-nums">
              {formatMoney(invoice.balance_due, i18n.language)}
            </span>
          </Link>
        </li>
      ))}
    </Panel>
  );
}
