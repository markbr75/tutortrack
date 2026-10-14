/** Time zones offered as a second calendar zone, and formatting in a zone (gap G3). */

export const COMMON_ZONES = [
  "Europe/London",
  "Europe/Dublin",
  "Europe/Paris",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Toronto",
  "Asia/Dubai",
  "Asia/Singapore",
  "Asia/Hong_Kong",
  "Australia/Sydney",
  "Pacific/Auckland",
];

/** The time of ``date`` in ``zone`` (e.g. "16:00"), in the viewer's locale. */
export function timeIn(date: Date, zone: string, locale: string): string {
  return date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", timeZone: zone });
}
