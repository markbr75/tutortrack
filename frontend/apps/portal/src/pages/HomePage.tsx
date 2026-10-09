import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api, usePortalMe } from "../api";
import { LessonCard } from "./LessonCard";

/** Next lesson, the week ahead, amount due, latest reports and news (FR-15-2). */
export function HomePage() {
  const { t, i18n } = useTranslation();
  const me = usePortalMe();
  const dash = useQuery({
    queryKey: ["portal", "dashboard"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/dashboard")),
  });
  if (dash.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  const d = dash.data;
  if (!d) return null;
  return (
    <div className="space-y-6">
      {me.data?.welcome_text ? <p className="text-sm">{me.data.welcome_text}</p> : null}
      {d.amount_due && Number(d.amount_due.amount) > 0 ? (
        <p className="rounded-lg bg-muted p-4">
          {t("portal.amountDue", { amount: formatMoney(d.amount_due, i18n.language) })}{" "}
          <Link to="/billing" className="font-medium underline">
            {t("portal.payNow")}
          </Link>
        </p>
      ) : null}
      <section aria-labelledby="next-lesson" className="space-y-2">
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
        <section aria-labelledby="this-week" className="space-y-2">
          <h2 id="this-week" className="font-semibold">
            {t("portal.thisWeek")}
          </h2>
          {d.upcoming.map((lesson) => (
            <LessonCard key={lesson.id} lesson={lesson} actions={false} />
          ))}
        </section>
      ) : null}
      {d.reports.length ? (
        <section aria-labelledby="latest-reports" className="space-y-2">
          <h2 id="latest-reports" className="font-semibold">
            {t("portal.latestReports")}
          </h2>
          <ul className="space-y-1 text-sm">
            {d.reports.map((r) => (
              <li key={r.id}>
                <Link to="/reports" className="underline-offset-2 hover:underline">
                  {r.lesson_title}
                </Link>{" "}
                · {formatDateTime(r.lesson_start, i18n.language)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {d.announcements.length ? (
        <section aria-labelledby="news" className="space-y-2">
          <h2 id="news" className="font-semibold">
            {t("portal.news")}
          </h2>
          {d.announcements.map((a) => (
            <article key={a.id} className="rounded-lg border border-border p-3">
              <h3 className="font-medium">{a.title}</h3>
              <p className="whitespace-pre-wrap text-sm">{a.body}</p>
            </article>
          ))}
        </section>
      ) : null}
    </div>
  );
}
