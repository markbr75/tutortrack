/** Calendar date helpers. Times are shown in the viewer's timezone (the browser's). */

export const DAY_MS = 86_400_000;

export function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

export function addDays(d: Date, n: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

/** Monday-based weeks. */
export function startOfWeek(d: Date): Date {
  const x = startOfDay(d);
  return addDays(x, -((x.getDay() + 6) % 7));
}

export function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

export function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

export function minutesOfDay(d: Date): number {
  return d.getHours() * 60 + d.getMinutes();
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** "2026-11-02" in local time (for date inputs). */
export function toDateInput(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** "16:30" in local time (for time inputs). */
export function toTimeInput(d: Date): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** A local date and time as a Date. */
export function fromInputs(date: string, time: string): Date {
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1, hh ?? 0, mm ?? 0);
}

export function viewerTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

export type View = "day" | "week" | "month" | "agenda" | "tutors";

/** The visible range [start, end) for a view around ``anchor``. */
export function rangeFor(view: View, anchor: Date): { start: Date; end: Date; days: Date[] } {
  if (view === "day" || view === "tutors") {
    const start = startOfDay(anchor);
    return { start, end: addDays(start, 1), days: [start] };
  }
  if (view === "week" || view === "agenda") {
    const start = startOfWeek(anchor);
    return {
      start,
      end: addDays(start, 7),
      days: Array.from({ length: 7 }, (_, i) => addDays(start, i)),
    };
  }
  const first = startOfWeek(startOfMonth(anchor));
  const days = Array.from({ length: 42 }, (_, i) => addDays(first, i));
  return { start: first, end: addDays(first, 42), days };
}

export function shift(view: View, anchor: Date, direction: 1 | -1): Date {
  if (view === "month") return new Date(anchor.getFullYear(), anchor.getMonth() + direction, 1);
  return addDays(anchor, (view === "week" || view === "agenda" ? 7 : 1) * direction);
}

const PALETTE = [
  "#2563eb",
  "#059669",
  "#d97706",
  "#7c3aed",
  "#db2777",
  "#0891b2",
  "#65a30d",
  "#dc2626",
];

export function colourFor(key: string): string {
  let hash = 0;
  for (const ch of key) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[hash % PALETTE.length] ?? "#2563eb";
}

export const STATUS_COLOURS: Record<string, string> = {
  planned: "#2563eb",
  completed: "#059669",
  cancelled: "#9ca3af",
  missed: "#dc2626",
};
