import { useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { useFeatures, useMe, usePermission } from "../api";
import { NewLesson } from "../calendar/NewLesson";
import { NeedsMarking, OverdueInvoices } from "../home/AttentionLists";
import { MoneyStrip } from "../home/MoneyStrip";
import { useTodaysLessons } from "../home/data";
import { TodaysRegister } from "../home/TodaysRegister";
import { Dashboard } from "../reporting/ReportingPages";
import { SetupChecklist } from "../success/SetupChecklist";

/** Figures Home already shows in its money strip, register and attention lists. */
const SHOWN_ABOVE = ["revenue", "outstanding", "next_pay_run", "upcoming_today", "unconfirmed"];

function nextHalfHour(): Date {
  const d = new Date();
  d.setMinutes(d.getMinutes() < 30 ? 30 : 60, 0, 0);
  return d;
}

function greetingKey(hour: number): string {
  if (hour < 12) return "home.greeting.morning";
  if (hour < 18) return "home.greeting.afternoon";
  return "home.greeting.evening";
}

/** What today holds: the register, money owed, and what still needs marking. */
export function HomePage() {
  const { t, i18n } = useTranslation();
  const [now] = useState(() => new Date());
  const { data: me } = useMe();
  const { data: features = {} } = useFeatures();
  const enabled = Object.entries(features).filter(([, on]) => on);
  const dashboard = usePermission("reporting.dashboard.view");
  const seeLessons = usePermission("scheduling.lesson.view");
  const markLessons = usePermission("scheduling.lesson.complete");
  const seeInvoices = usePermission("billing.invoice.view");
  const addFamily = usePermission("people.client.create");
  const bookLesson = usePermission("scheduling.lesson.create");
  const [booking, setBooking] = useState<Date | null>(null);
  const today = useTodaysLessons(now, seeLessons);
  const lessons = seeLessons ? (today.data ?? []) : [];
  const tutors = new Set(lessons.flatMap((l) => l.tutors.map((tutor) => tutor.tutor))).size;
  const date = new Intl.DateTimeFormat(i18n.language, {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(now);
  const name = me?.user.first_name;

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">
            {name ? t(greetingKey(now.getHours()), { name }) : t("home.title")}
          </h1>
          <p className="mt-1 text-muted-foreground">
            {seeLessons && today.data
              ? t("home.todaySummary", { date, count: lessons.length, tutors })
              : date}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {addFamily ? (
            <Link
              to="/clients/new"
              className="inline-flex h-10 items-center rounded-md border border-border bg-surface px-4 text-sm font-medium hover:bg-muted"
            >
              {t("home.addFamily")}
            </Link>
          ) : null}
          {bookLesson ? (
            <Button onClick={() => setBooking(nextHalfHour())}>{t("home.bookLesson")}</Button>
          ) : null}
        </div>
      </header>
      <SetupChecklist />
      <MoneyStrip />
      {seeLessons || markLessons || seeInvoices ? (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
          {seeLessons ? <TodaysRegister now={now} /> : <div />}
          <div className="space-y-6">
            {markLessons ? <NeedsMarking now={now} /> : null}
            {seeInvoices ? <OverdueInvoices /> : null}
          </div>
        </div>
      ) : null}
      {dashboard ? <Dashboard hide={SHOWN_ABOVE} /> : null}
      <section aria-labelledby="features-h" className="border-t border-border pt-4">
        <h2 id="features-h" className="text-sm font-semibold">
          {t("home.features")}
        </h2>
        {enabled.length === 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">{t("home.noFeatures")}</p>
        ) : (
          <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
            {enabled.map(([key]) => (
              <li key={key}>{t(`plan.features.${key}`, { defaultValue: key })}</li>
            ))}
          </ul>
        )}
      </section>
      {bookLesson ? <NewLesson start={booking} onClose={() => setBooking(null)} /> : null}
    </section>
  );
}
