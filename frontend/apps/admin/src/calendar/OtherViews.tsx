import { RegisterMark, registerMarkFor } from "@tutortrack/ui";
import { formatDate, useTranslation } from "@tutortrack/i18n";

import { timeIn } from "../g3/zones";
import { sameDay } from "./dates";
import type { CalendarItem } from "./types";

function time(iso: string, locale: string): string {
  return new Date(iso).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
}

export function MonthView({
  days,
  month,
  items,
  colour,
  onSelect,
  onDay,
}: {
  days: Date[];
  month: number;
  items: CalendarItem[];
  colour: (item: CalendarItem) => string;
  onSelect: (item: CalendarItem) => void;
  onDay: (day: Date) => void;
}) {
  const { t, i18n } = useTranslation();
  const weekdays = days
    .slice(0, 7)
    .map((d) => d.toLocaleDateString(i18n.language, { weekday: "short" }));
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] table-fixed border-collapse text-xs">
        <caption className="sr-only">{t("calendar.views.month")}</caption>
        <thead>
          <tr>
            {weekdays.map((w) => (
              <th key={w} scope="col" className="border border-border p-1 font-medium">
                {w}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: 6 }, (_, week) => (
            <tr key={week}>
              {days.slice(week * 7, week * 7 + 7).map((day) => {
                const dayItems = items.filter((i) => sameDay(new Date(i.start), day));
                return (
                  <td
                    key={day.toISOString()}
                    className={`h-24 border border-border p-1 align-top ${day.getMonth() === month ? "bg-surface" : "bg-muted/40 text-muted-foreground"}`}
                  >
                    <button
                      type="button"
                      aria-current={sameDay(day, new Date()) ? "date" : undefined}
                      className="mb-1 text-xs font-medium hover:underline aria-[current=date]:font-semibold aria-[current=date]:text-margin"
                      aria-label={t("calendar.openDay", {
                        day: formatDate(day.toISOString(), i18n.language),
                      })}
                      onClick={() => onDay(day)}
                    >
                      {day.getDate()}
                    </button>
                    <ul className="space-y-0.5">
                      {dayItems.slice(0, 4).map((item) => (
                        <li key={`${item.kind}-${item.id}`}>
                          <button
                            type="button"
                            className={`block w-full truncate rounded border px-1 text-left text-foreground ${item.status === "cancelled" ? "line-through opacity-70" : ""}`}
                            style={{
                              background: `color-mix(in srgb, ${colour(item)} 16%, hsl(var(--tt-surface)))`,
                              borderColor: colour(item),
                            }}
                            onClick={() => onSelect(item)}
                          >
                            {time(item.start, i18n.language)} {item.title}
                          </button>
                        </li>
                      ))}
                      {dayItems.length > 4 ? (
                        <li className="text-muted-foreground">
                          {t("calendar.more", { count: dayItems.length - 4 })}
                        </li>
                      ) : null}
                    </ul>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AgendaView({
  days,
  items,
  colour,
  onSelect,
  selected,
  onToggle,
  secondaryZone,
}: {
  days: Date[];
  items: CalendarItem[];
  colour: (item: CalendarItem) => string;
  onSelect: (item: CalendarItem) => void;
  /** Gap G3: lessons chosen for bulk actions (checkboxes show when given). */
  selected?: string[];
  onToggle?: (id: string) => void;
  /** Gap G3: also show times in this timezone. */
  secondaryZone?: string;
}) {
  const { t, i18n } = useTranslation();
  const withItems = days
    .map((day) => ({
      day,
      // In time order within the day, whatever order the API sent.
      items: items
        .filter((i) => sameDay(new Date(i.start), day))
        .sort((a, b) => a.start.localeCompare(b.start)),
    }))
    .filter((d) => d.items.length);
  if (!withItems.length)
    return <p className="text-sm text-muted-foreground">{t("calendar.nothing")}</p>;
  return (
    <div className="space-y-4">
      {withItems.map(({ day, items: dayItems }) => (
        <section key={day.toISOString()}>
          <h2
            aria-current={sameDay(day, new Date()) ? "date" : undefined}
            className="mb-2 text-base font-semibold aria-[current=date]:text-margin"
          >
            {day.toLocaleDateString(i18n.language, {
              weekday: "long",
              day: "numeric",
              month: "long",
            })}
          </h2>
          <ul className="divide-y divide-rule rounded-xl border border-border bg-surface">
            {dayItems.map((item) => (
              <li key={`${item.kind}-${item.id}`} className="flex items-start">
                {onToggle && item.kind === "lesson" ? (
                  <input
                    type="checkbox"
                    className="ml-2 mt-3 size-4 shrink-0"
                    aria-label={t("g3.calendar.selectLesson", { title: item.title })}
                    checked={selected?.includes(item.id) ?? false}
                    onChange={() => onToggle(item.id)}
                  />
                ) : null}
                <button
                  type="button"
                  className="flex w-full items-start gap-3 px-4 py-2.5 text-left text-sm hover:bg-muted/60"
                  onClick={() => onSelect(item)}
                >
                  <span
                    aria-hidden="true"
                    className="mt-1 size-3 shrink-0 rounded-full"
                    style={{ background: colour(item) }}
                  />
                  <span className="w-28 shrink-0 tabular-nums">
                    {time(item.start, i18n.language)}–{time(item.end, i18n.language)}
                    {secondaryZone ? (
                      <span className="block text-xs text-muted-foreground">
                        {timeIn(new Date(item.start), secondaryZone, i18n.language)}{" "}
                        {secondaryZone.split("/").pop()?.replace("_", " ")}
                      </span>
                    ) : null}
                  </span>
                  <span
                    className={`min-w-0 flex-1 ${item.status === "cancelled" ? "line-through" : ""}`}
                  >
                    <span className="font-medium">{item.title}</span>
                    <span className="block text-muted-foreground">
                      {[
                        item.tutors.map((p) => p.name).join(", "),
                        item.online ? t("calendar.online") : item.location,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                      {item.status !== "planned"
                        ? ` · ${t(`calendar.status.${item.status}`, { defaultValue: item.status })}`
                        : ""}
                    </span>
                  </span>
                  {item.kind === "lesson" ? (
                    <RegisterMark
                      kind={registerMarkFor(item.status, item.end)}
                      label={t(`calendar.status.${item.status}`, { defaultValue: item.status })}
                      className="mt-0.5"
                    />
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
