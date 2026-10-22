import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Button, cn, RegisterMark, registerMarkFor, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Fragment, useEffect, useState } from "react";

import { api } from "../api";
import { PanelEmpty, PortalHeader } from "../layout/PortalPage";
import { PlanLessonForm } from "./Planning";
import { useTutorMe } from "./useTutorMe";

function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

/** The next two weeks (and yesterday) as one register (E16-T02): a ruled panel whose days are
 * divider rows (today's in margin red), each lesson a row with its time, title, one line of
 * context and its register mark, and on today the NOW rule between past and coming lessons.
 * A lesson that is over and still to mark carries the red dashed mark. */
export function TutorSchedulePage() {
  const { t, i18n } = useTranslation();
  const me = useTutorMe();
  const now = useNow();
  const [planning, setPlanning] = useState(false);
  const [range] = useState(() => {
    const start = new Date();
    start.setDate(start.getDate() - 1);
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(end.getDate() + 15);
    return { start: start.toISOString(), end: end.toISOString() };
  });
  const items = useQuery({
    queryKey: ["tutor", "schedule", range.start],
    enabled: Boolean(me.data),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/calendar", {
          params: { query: { start: range.start, end: range.end, tutor: [me.data!.id] } },
        }),
      ),
  });
  if (items.isPending) return <Spinner label={t("grid.loading")} />;
  const lessons = (items.data ?? [])
    .filter((item) => item.kind === "lesson")
    .sort((a, b) => a.start.localeCompare(b.start));
  const days = new Map<string, typeof lessons>();
  for (const lesson of lessons) {
    const key = new Date(lesson.start).toDateString();
    days.set(key, [...(days.get(key) ?? []), lesson]);
  }
  const today = now.toDateString();
  const clock = (iso: string) =>
    formatDateTime(iso, i18n.language, undefined, { hour: "2-digit", minute: "2-digit" });
  const nowRule = (
    <li aria-hidden="true" className="border-t-2 border-margin">
      <span className="block px-4 py-1 text-xs font-semibold tracking-wider text-margin uppercase">
        {t("tutorToday.now", { time: clock(now.toISOString()) })}
      </span>
    </li>
  );
  return (
    <div>
      <PortalHeader
        title={t("tutor.nav.schedule")}
        actions={
          me.data?.can_create_lessons && !planning ? (
            <Button size="sm" onClick={() => setPlanning(true)}>
              {t("tutorPlan.newLesson")}
            </Button>
          ) : null
        }
      />
      <div className="space-y-6">
        {planning ? <PlanLessonForm onDone={() => setPlanning(false)} /> : null}
        <section
          aria-label={t("tutor.nav.schedule")}
          className="overflow-hidden rounded-xl border border-border bg-surface"
        >
          {!lessons.length ? <PanelEmpty>{t("portal.noLessons")}</PanelEmpty> : null}
          <ol>
            {[...days.entries()].map(([day, rows], dayIndex) => {
              const isToday = day === today;
              const headingId = `day-${rows[0]!.id}`;
              // On today, the NOW rule goes before the first lesson that has not ended.
              const nowIndex = isToday ? rows.findIndex((l) => new Date(l.end) > now) : -2;
              return (
                <Fragment key={day}>
                  <li className={cn("px-4 pt-3 pb-1", dayIndex > 0 && "border-t border-border")}>
                    <h2
                      id={headingId}
                      aria-current={isToday ? "date" : undefined}
                      className={cn(
                        "text-xs font-semibold",
                        isToday ? "text-margin" : "text-muted-foreground",
                      )}
                    >
                      {new Date(rows[0]!.start).toLocaleDateString(i18n.language, {
                        weekday: "long",
                        day: "numeric",
                        month: "long",
                      })}
                    </h2>
                  </li>
                  {rows.map((lesson, index) => {
                    const kind = registerMarkFor(lesson.status, lesson.end, now);
                    const context = [
                      lesson.students.map((s) => s.name).join(", "),
                      lesson.online ? t("portal.online") : lesson.room_name || lesson.location,
                    ]
                      .filter(Boolean)
                      .join(" · ");
                    return (
                      <Fragment key={lesson.id}>
                        {index === nowIndex ? nowRule : null}
                        <li
                          className={cn(index > 0 && index !== nowIndex && "border-t border-rule")}
                        >
                          <Link
                            to="/tutor/lessons/$lessonId"
                            params={{ lessonId: lesson.id }}
                            aria-describedby={headingId}
                            className="flex items-center gap-3 px-4 py-3 hover:bg-muted/60"
                          >
                            <span className="w-14 shrink-0 tabular-nums">
                              <time dateTime={lesson.start} className="block font-semibold">
                                {clock(lesson.start)}
                              </time>
                              <time
                                dateTime={lesson.end}
                                className="block text-xs text-muted-foreground"
                              >
                                {clock(lesson.end)}
                              </time>
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block font-medium">{lesson.title}</span>
                              {context ? (
                                <span className="block text-xs text-muted-foreground">
                                  {context}
                                </span>
                              ) : null}
                            </span>
                            <RegisterMark
                              kind={kind}
                              label={
                                kind === "due"
                                  ? t("designS10.toMark")
                                  : t(`portal.status.${lesson.status}`, {
                                      defaultValue: lesson.status,
                                    })
                              }
                            />
                          </Link>
                        </li>
                      </Fragment>
                    );
                  })}
                  {isToday && nowIndex === -1 ? nowRule : null}
                </Fragment>
              );
            })}
          </ol>
        </section>
      </div>
    </div>
  );
}
