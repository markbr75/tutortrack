import { type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { RegisterMark, registerMarkFor, type RegisterMarkKind } from "@tutortrack/ui";
import { Link } from "@tanstack/react-router";
import { Fragment } from "react";

import { useTodaysLessons } from "./data";

type Lesson = components["schemas"]["Lesson"];

const MARK_LABEL: Record<RegisterMarkKind, string> = {
  completed: "home.register.marks.completed",
  missed: "home.register.marks.missed",
  cancelled: "home.register.marks.cancelled",
  due: "home.register.marks.due",
  upcoming: "home.register.marks.upcoming",
};

/** Today's lessons in time order, each with its register mark; the red rule marks now. */
export function TodaysRegister({ now = new Date() }: { now?: Date }) {
  const { t, i18n } = useTranslation();
  const lessons = useTodaysLessons(now);
  const rows: Lesson[] = lessons.data ?? [];
  const time = (iso: string) =>
    formatDateTime(iso, i18n.language, undefined, { hour: "2-digit", minute: "2-digit" });
  const marked = rows.filter((l) => l.status !== "planned").length;
  // The rule sits before the first lesson that has not ended yet.
  const nowIndex = rows.findIndex((l) => new Date(l.end) > now);
  const nowRule = (
    <tr aria-hidden="true" className="border-t-2 border-margin">
      <td
        colSpan={4}
        className="py-1 pl-5 text-xs font-semibold tracking-wider text-margin uppercase"
      >
        {t("home.register.now", { time: time(now.toISOString()) })}
      </td>
    </tr>
  );

  return (
    <section aria-labelledby="register-h" className="rounded-xl border border-border bg-surface">
      <div className="flex items-baseline justify-between gap-4 border-b border-border px-5 py-3.5">
        <h2 id="register-h" className="text-base font-semibold">
          {t("home.register.title")}
        </h2>
        {rows.length ? (
          <p className="text-sm text-muted-foreground">
            {t("home.register.marked", { done: marked, total: rows.length })}
          </p>
        ) : null}
      </div>
      {lessons.isPending ? (
        <div aria-hidden="true" className="space-y-3 p-5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-8 animate-pulse rounded bg-muted" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <div className="px-5 py-8 text-sm">
          <p className="text-muted-foreground">{t("home.register.empty")}</p>
          <Link to="/calendar" className="mt-2 inline-block font-medium text-brand hover:underline">
            {t("home.register.openCalendar")}
          </Link>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th scope="col" className="w-24 py-2 pr-3 pl-5 font-semibold">
                  {t("home.register.time")}
                </th>
                <th scope="col" className="py-2 pr-3 font-semibold">
                  {t("home.register.lesson")}
                </th>
                <th scope="col" className="py-2 pr-3 font-semibold max-sm:hidden">
                  {t("home.register.tutor")}
                </th>
                <th scope="col" className="w-20 py-2 pr-5 text-center font-semibold">
                  {t("home.register.mark")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((lesson, index) => {
                const kind = registerMarkFor(lesson.status, lesson.end, now);
                const students = lesson.attendees.map((a) => a.name).join(", ");
                const where = lesson.online ? t("home.register.online") : lesson.location || "";
                const tutors = lesson.tutors.map((tutor) => tutor.name).join(", ");
                return (
                  <Fragment key={lesson.id}>
                    {index === nowIndex ? nowRule : null}
                    <tr className="border-t border-rule align-middle">
                      <td className="py-2.5 pr-3 pl-5 font-semibold">
                        <time dateTime={lesson.start}>{time(lesson.start)}</time>
                      </td>
                      <td className="py-2.5 pr-3">
                        <span className="block">{lesson.title}</span>
                        <span className="block text-xs text-muted-foreground">
                          {[students, where].filter(Boolean).join(" · ")}
                        </span>
                        {/* Phones drop the tutor column; the tutor reads here instead. */}
                        <span className="block text-xs text-muted-foreground sm:hidden">
                          {tutors}
                        </span>
                      </td>
                      <td className="py-2.5 pr-3 max-sm:hidden">{tutors}</td>
                      <td className="py-2.5 pr-5">
                        <RegisterMark kind={kind} label={t(MARK_LABEL[kind])} className="mx-auto" />
                      </td>
                    </tr>
                  </Fragment>
                );
              })}
              {nowIndex === -1 ? nowRule : null}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
