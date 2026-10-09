import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api";
import { useTutorMe } from "./useTutorMe";

/** The next two weeks (and yesterday) as an agenda (E16-T02). */
export function TutorSchedulePage() {
  const { t, i18n } = useTranslation();
  const me = useTutorMe();
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
  if (items.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  const lessons = (items.data ?? []).filter((item) => item.kind === "lesson");
  const days = new Map<string, typeof lessons>();
  for (const lesson of lessons) {
    const key = new Date(lesson.start).toDateString();
    days.set(key, [...(days.get(key) ?? []), lesson]);
  }
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{t("tutor.nav.schedule")}</h1>
      {!lessons.length ? (
        <p className="text-sm text-muted-foreground">{t("portal.noLessons")}</p>
      ) : null}
      {[...days.entries()].map(([day, rows]) => (
        <section
          key={day}
          aria-label={new Date(rows[0]!.start).toLocaleDateString(i18n.language, {
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        >
          <h2 className="font-semibold">
            {new Date(rows[0]!.start).toLocaleDateString(i18n.language, {
              weekday: "long",
              day: "numeric",
              month: "long",
            })}
          </h2>
          <ul className="mt-1 space-y-1">
            {rows.map((lesson) => (
              <li key={lesson.id}>
                <Link
                  to="/tutor/lessons/$lessonId"
                  params={{ lessonId: lesson.id }}
                  className="flex justify-between rounded-md border border-border p-3 text-sm"
                >
                  <span>
                    {new Date(lesson.start).toLocaleTimeString(i18n.language, {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    · {lesson.title}
                  </span>
                  <span className="text-muted-foreground">
                    {t(`portal.status.${lesson.status}`)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
