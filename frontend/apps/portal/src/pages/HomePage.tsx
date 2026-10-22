import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { buttonClass, RegisterMark, registerMarkFor, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api, usePortalMe } from "../api";
import { isPositive, sumAmounts } from "../money";
import { LessonCard, type PortalLesson } from "./LessonCard";

/** Next lesson, the week ahead, amount due, latest reports and news (FR-15-2). */
export function HomePage() {
  const { t, i18n } = useTranslation();
  const me = usePortalMe();
  const dash = useQuery({
    queryKey: ["portal", "dashboard"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/dashboard")),
  });
  if (dash.isPending) return <Spinner label={t("grid.loading")} />;
  const d = dash.data;
  if (!d) return null;
  return (
    <div className="space-y-8">
      {me.data?.welcome_text ? (
        <p className="text-sm text-muted-foreground">{me.data.welcome_text}</p>
      ) : null}
      {d.amount_due && Number(d.amount_due.amount) > 0 ? (
        // One ruled line of money, like the register's money strip.
        <div className="flex items-center justify-between gap-4 border-y border-border py-3">
          <div className="min-w-0">
            <p className="font-semibold tabular-nums">
              {t("portal.amountDue", { amount: formatMoney(d.amount_due, i18n.language) })}
            </p>
            <OverdueNote currency={d.amount_due.currency} />
          </div>
          <Link to="/billing" className={buttonClass()}>
            {t("portal.payNow")}
          </Link>
        </div>
      ) : null}
      <section aria-labelledby="next-lesson" className="space-y-3">
        <h1 id="next-lesson" className="text-xl font-semibold">
          {t("portal.nextLesson")}
        </h1>
        {d.next_lesson ? (
          <LessonCard lesson={d.next_lesson} />
        ) : (
          <p className="text-sm text-muted-foreground">{t("portal.noLessons")}</p>
        )}
      </section>
      {d.upcoming.length ? (
        <section aria-labelledby="this-week" className="space-y-3">
          <div className="flex items-baseline justify-between gap-4">
            <h2 id="this-week" className="text-base font-semibold">
              {t("portal.thisWeek")}
            </h2>
            <Link to="/schedule" className="text-sm font-medium text-link hover:underline">
              {t("portalHome.allLessons")}
            </Link>
          </div>
          <WeekRows lessons={d.upcoming} />
        </section>
      ) : null}
      {d.reports.length ? (
        <section aria-labelledby="latest-reports" className="space-y-3">
          <h2 id="latest-reports" className="text-base font-semibold">
            {t("portal.latestReports")}
          </h2>
          <ul className="divide-y divide-rule rounded-xl border border-border bg-surface">
            {d.reports.map((r) => (
              <li key={r.id}>
                <Link
                  to="/reports"
                  className="flex items-baseline justify-between gap-4 px-4 py-3 hover:bg-muted/60"
                >
                  <span className="min-w-0 font-medium">{r.lesson_title}</span>
                  <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                    {formatDateTime(r.lesson_start, i18n.language, undefined, {
                      day: "numeric",
                      month: "short",
                    })}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {d.announcements.length ? (
        <section aria-labelledby="news" className="space-y-3">
          <h2 id="news" className="text-base font-semibold">
            {t("portal.news")}
          </h2>
          <div className="divide-y divide-rule rounded-xl border border-border bg-surface">
            {d.announcements.map((a) => (
              <article key={a.id} className="space-y-1 px-4 py-3">
                <h3 className="font-medium">{a.title}</h3>
                <p className="text-sm whitespace-pre-wrap text-muted-foreground">{a.body}</p>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

/** Under the owed line, only while part of it is past due: how much, in margin red. Owing
 * alone is not overdue, so nothing shows otherwise. */
function OverdueNote({ currency }: { currency: string }) {
  const { t, i18n } = useTranslation();
  const me = usePortalMe();
  const billing = useQuery({
    queryKey: ["portal", "billing"],
    enabled: Boolean(me.data?.features.invoices),
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/billing")),
  });
  const overdue = sumAmounts(
    (billing.data?.accounts ?? [])
      .map((account) => account.balances.overdue)
      .filter((money) => money.currency === currency)
      .map((money) => money.amount),
  );
  if (!isPositive(overdue)) return null;
  return (
    <p className="text-sm font-medium text-margin tabular-nums">
      {t("designS10.overdueOfIt", {
        amount: formatMoney({ amount: overdue, currency }, i18n.language),
      })}
    </p>
  );
}

/** The week ahead as register rows: day and time, the lesson, its mark. */
function WeekRows({ lessons }: { lessons: ReadonlyArray<PortalLesson> }) {
  const { t, i18n } = useTranslation();
  const at = (iso: string, options: Intl.DateTimeFormatOptions) =>
    formatDateTime(iso, i18n.language, undefined, options);
  return (
    <ul className="divide-y divide-rule rounded-xl border border-border bg-surface">
      {lessons.map((lesson) => (
        <li key={lesson.id} className="flex items-center gap-4 px-4 py-3">
          <p className="w-16 shrink-0 tabular-nums">
            <span className="block text-xs text-muted-foreground">
              {at(lesson.start, { weekday: "short", day: "numeric" })}
            </span>
            <time dateTime={lesson.start} className="block font-semibold">
              {at(lesson.start, { hour: "2-digit", minute: "2-digit" })}
            </time>
          </p>
          <div className="min-w-0 flex-1">
            <p className="font-medium">{lesson.title}</p>
            <p className="text-xs text-muted-foreground">
              {[
                lesson.tutors.map((tutor) => tutor.name).join(", "),
                lesson.online ? t("portal.online") : lesson.location,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
          <RegisterMark
            kind={registerMarkFor(lesson.status, lesson.end)}
            label={t(`portal.status.${lesson.status}`)}
            className="shrink-0"
          />
        </li>
      ))}
    </ul>
  );
}
