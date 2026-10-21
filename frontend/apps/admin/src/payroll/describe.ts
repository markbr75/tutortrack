/** Pay item descriptions end with the lesson's ISO date ("… · 2026-10-17"); screens that show
 * the date formatted beside them drop that duplicate. Other descriptions are left as they are. */
export function withoutIsoDate(description: string, date?: string | null): string {
  if (!date) return description;
  const suffix = ` · ${date}`;
  return description.endsWith(suffix) ? description.slice(0, -suffix.length) : description;
}
