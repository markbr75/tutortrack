import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { buttonClass, RegisterMark, registerMarkFor, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { Fragment, useEffect, useState } from "react";

import { api } from "../api";
import { JoinButton } from "../JoinButton";
import { useTutorMe } from "./useTutorMe";

function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

function localDate(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Today's register with join and complete, then what is waiting (E16-T01). */
export function TodayPage() {
  const { t, i18n } = useTranslation();
  const me = useTutorMe();
  const now = useNow();
  const today = useQuery({
    queryKey: ["tutor", "today"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tutor/today")),
  });
  if (today.isPending) return <Spinner label={t("grid.loading")} />;
  const d = today.data;
  if (!d) return null;
  const clock = (iso: string) =>
    formatDateTime(iso, i18n.language, undefined, { hour: "2-digit", minute: "2-digit" });
  const marked = d.lessons.filter((lesson) => lesson.status !== "planned").length;
  // The red rule sits before the first lesson that has not ended, on today's page only.
  const isToday = d.date === localDate(now);
  const nowIndex = isToday ? d.lessons.findIndex((l) => new Date(l.end) > now) : -2;
  const nowRule = (
    <li aria-hidden="true" className="border-t-2 border-margin">
      <span className="block px-4 py-1 text-xs font-semibold tracking-wider text-margin uppercase">
        {t("tutorToday.now", { time: clock(now.toISOString()) })}
      </span>
    </li>
  );
  // The tab's pill counts lessons still to mark on earlier days too; name those here, as
  // today's sit in the register above.
  const dueToday = d.lessons.filter(
    (lesson) => lesson.status === "planned" && new Date(lesson.end) <= now,
  ).length;
  const earlier = Math.max(0, (d.unmarked_lessons ?? dueToday) - dueToday);
  const waiting = [
    { count: earlier, label: t("tutor.earlierToMark"), to: "/tutor/schedule" },
    { count: d.reports_due, label: t("tutor.reportsDue"), to: "/tutor/schedule" },
    { count: d.offers, label: t("tutor.offers"), to: "/tutor/jobs" },
    { count: d.unread, label: t("tutor.unread"), to: "/tutor/notifications" },
  ].filter((item) => item.count > 0);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold">{t("tutor.today")}</h1>
        <p className="text-sm text-muted-foreground">
          {formatDateTime(`${d.date}T12:00:00`, i18n.language, undefined, {
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        </p>
      </div>

      <section
        aria-labelledby="today-lessons"
        className="rounded-xl border border-border bg-surface"
      >
        <div
          className={`flex items-baseline justify-between gap-4 px-4 py-3 ${nowIndex === 0 ? "" : "border-b border-border"}`}
        >
          <h2 id="today-lessons" className="text-base font-semibold">
            {t("tutorToday.lessons")}
          </h2>
          {d.lessons.length ? (
            <p className="text-sm text-muted-foreground">
              {t("tutorToday.marked", { done: marked, total: d.lessons.length })}
            </p>
          ) : null}
        </div>
        {d.lessons.length ? (
          <ol>
            {d.lessons.map((lesson, index) => {
              const kind = registerMarkFor(lesson.status, lesson.end, now);
              return (
                <Fragment key={lesson.id}>
                  {index === nowIndex ? nowRule : null}
                  <li className="flex gap-3 border-t border-rule px-4 py-3 first:border-t-0">
                    <p className="w-14 shrink-0 tabular-nums">
                      <time dateTime={lesson.start} className="block font-semibold">
                        {clock(lesson.start)}
                      </time>
                      <time dateTime={lesson.end} className="block text-xs text-muted-foreground">
                        {clock(lesson.end)}
                      </time>
                    </p>
                    <div className="min-w-0 flex-1 space-y-2">
                      <div>
                        <p className="font-medium">{lesson.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {[
                            lesson.students.join(", "),
                            lesson.online ? t("portal.online") : lesson.location,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {lesson.online && lesson.status === "planned" ? (
                          <JoinButton
                            url={lesson.join_url || lesson.meeting_url}
                            start={lesson.start}
                            end={lesson.end}
                            opensAt={lesson.join_opens_at}
                          />
                        ) : null}
                        <Link
                          to="/tutor/lessons/$lessonId"
                          params={{ lessonId: lesson.id }}
                          className={buttonClass({
                            variant: kind === "due" ? "primary" : "secondary",
                          })}
                        >
                          {lesson.status === "planned"
                            ? t("tutor.openToComplete")
                            : t("tutor.open")}
                          <span className="sr-only"> {lesson.title}</span>
                        </Link>
                      </div>
                    </div>
                    <RegisterMark
                      kind={kind}
                      label={t(`portal.status.${lesson.status}`)}
                      className="mt-0.5 shrink-0"
                    />
                  </li>
                </Fragment>
              );
            })}
            {nowIndex === -1 ? nowRule : null}
          </ol>
        ) : (
          <p className="px-4 py-6 text-sm text-muted-foreground">{t("tutor.noLessonsToday")}</p>
        )}
      </section>

      <section
        aria-labelledby="waiting"
        className="overflow-hidden rounded-xl border border-border bg-surface"
      >
        <h2
          id="waiting"
          className={`border-b px-4 py-3 text-base font-semibold ${waiting.length ? "border-margin" : "border-border"}`}
        >
          {t("tutorToday.waiting")}
        </h2>
        {waiting.length ? (
          <ul className="divide-y divide-rule">
            {waiting.map((item) => (
              <li key={item.label}>
                <Link
                  to={item.to}
                  className="flex min-h-12 items-center gap-3 px-4 hover:bg-muted/60"
                >
                  <span className="flex-1">{item.label}</span>
                  <span className="font-semibold text-margin tabular-nums">{item.count}</span>
                  <ChevronRight aria-hidden="true" className="size-4 text-muted-foreground" />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-4 py-6 text-sm text-muted-foreground">
            {t("tutorToday.nothingWaiting")}
          </p>
        )}
      </section>

      {me.data?.can_see_pay ? (
        <div className="flex items-end justify-between gap-4 border-y border-border py-3">
          <Link
            to="/tutor/earnings"
            className="text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            {t("tutor.thisMonth")}
          </Link>
          <p className="text-xl font-semibold tabular-nums">
            {formatMoney(d.earnings_this_month, i18n.language)}
          </p>
        </div>
      ) : null}
    </div>
  );
}
