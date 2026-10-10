import { unwrap } from "@tutortrack/api-client";
import { formatMoney, useTranslation } from "@tutortrack/i18n";
import { Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api } from "../api";
import { JoinButton } from "../JoinButton";
import { useTutorMe } from "./useTutorMe";

function time(iso: string, locale: string) {
  return new Date(iso).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
}

/** Today's lessons with join and complete, and what needs doing (E16-T01). */
export function TodayPage() {
  const { t, i18n } = useTranslation();
  const me = useTutorMe();
  const today = useQuery({
    queryKey: ["tutor", "today"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tutor/today")),
  });
  if (today.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  const d = today.data;
  if (!d) return null;
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">{t("tutor.today")}</h1>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="rounded-lg bg-muted p-3">
          <dt className="text-xs text-muted-foreground">{t("tutor.reportsDue")}</dt>
          <dd className="text-lg font-semibold">{d.reports_due}</dd>
        </div>
        <div className="rounded-lg bg-muted p-3">
          <dt className="text-xs text-muted-foreground">{t("tutor.offers")}</dt>
          <dd className="text-lg font-semibold">{d.offers}</dd>
        </div>
        <div className="rounded-lg bg-muted p-3">
          <dt className="text-xs text-muted-foreground">{t("tutor.unread")}</dt>
          <dd className="text-lg font-semibold">{d.unread}</dd>
        </div>
        {me.data?.can_see_pay ? (
          <div className="rounded-lg bg-muted p-3">
            <dt className="text-xs text-muted-foreground">{t("tutor.thisMonth")}</dt>
            <dd className="text-lg font-semibold">
              {formatMoney(d.earnings_this_month, i18n.language)}
            </dd>
          </div>
        ) : null}
      </dl>
      {d.lessons.length ? (
        <ol className="space-y-2">
          {d.lessons.map((lesson) => {
            return (
              <li key={lesson.id} className="rounded-lg border border-border p-3">
                <p className="text-sm text-muted-foreground">
                  {time(lesson.start, i18n.language)}–{time(lesson.end, i18n.language)} ·{" "}
                  {t(`portal.status.${lesson.status}`)}
                </p>
                <p className="font-medium">{lesson.title}</p>
                <p className="text-sm">
                  {lesson.students.join(", ")}
                  {lesson.online
                    ? ` · ${t("portal.online")}`
                    : lesson.location
                      ? ` · ${lesson.location}`
                      : ""}
                </p>
                <div className="mt-2 flex flex-wrap gap-2 text-sm">
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
                    className="rounded-md border border-border px-3 py-2"
                  >
                    {lesson.status === "planned" ? t("tutor.openToComplete") : t("tutor.open")}
                    <span className="sr-only"> {lesson.title}</span>
                  </Link>
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="text-sm text-muted-foreground">{t("tutor.noLessonsToday")}</p>
      )}
    </div>
  );
}
