import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Button, cn, RegisterMark, registerMarkFor, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";
import { PortalHeader } from "../layout/PortalPage";
import { PlanLessonForm } from "./Planning";
import { useTutorMe } from "./useTutorMe";

/** The next two weeks (and yesterday) as an agenda (E16-T02): one ruled register panel per
 * day under its date (today's in margin red), each lesson a row with its time, title, one
 * line of context and its register mark; lessons over and still to mark carry the red mark. */
export function TutorSchedulePage() {
  const { t, i18n } = useTranslation();
  const me = useTutorMe();
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
  const lessons = (items.data ?? []).filter((item) => item.kind === "lesson");
  const days = new Map<string, typeof lessons>();
  for (const lesson of lessons) {
    const key = new Date(lesson.start).toDateString();
    days.set(key, [...(days.get(key) ?? []), lesson]);
  }
  const today = new Date().toDateString();
  const clock = (iso: string) =>
    formatDateTime(iso, i18n.language, undefined, { hour: "2-digit", minute: "2-digit" });
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
        {!lessons.length ? (
          <p className="text-sm text-muted-foreground">{t("portal.noLessons")}</p>
        ) : null}
        {[...days.entries()].map(([day, rows]) => {
          const isToday = day === today;
          const headingId = `day-${rows[0]!.id}`;
          return (
            <section key={day} aria-labelledby={headingId} className="space-y-2">
              <h2
                id={headingId}
                aria-current={isToday ? "date" : undefined}
                className={cn("text-base font-semibold", isToday && "text-margin")}
              >
                {new Date(rows[0]!.start).toLocaleDateString(i18n.language, {
                  weekday: "long",
                  day: "numeric",
                  month: "long",
                })}
              </h2>
              <ul className="divide-y divide-rule overflow-hidden rounded-xl border border-border bg-surface">
                {rows.map((lesson) => {
                  const kind = registerMarkFor(lesson.status, lesson.end);
                  const place = lesson.online
                    ? t("portal.online")
                    : lesson.room_name || lesson.location;
                  return (
                    <li key={lesson.id}>
                      <Link
                        to="/tutor/lessons/$lessonId"
                        params={{ lessonId: lesson.id }}
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
                          {place ? (
                            <span className="block text-xs text-muted-foreground">{place}</span>
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
                  );
                })}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}
