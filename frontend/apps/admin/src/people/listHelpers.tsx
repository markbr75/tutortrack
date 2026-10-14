import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import type { ColumnDef } from "@tutortrack/ui";
import { useState } from "react";

/** Gap batch G1 (FR-05-11/12): helpers for the people list grids (figures, row selection). */

export type BulkEntity = "client" | "contact" | "student" | "tutor";

export const actionLink =
  "inline-flex h-10 items-center rounded-md border border-border px-4 text-sm hover:bg-muted";

/** "12.5 h", "—" when the figure isn't available to the viewer. */
export function useFigures() {
  const { t, i18n } = useTranslation();
  const none = t("peopleTools.columns.none");
  return {
    money: (amount: string | null | undefined, currency: string | null | undefined) =>
      amount == null ? none : formatMoney({ amount, currency: currency ?? "GBP" }, i18n.language),
    date: (iso: string | null | undefined) => (iso ? formatDate(iso, i18n.language) : none),
    hours: (value: string | null | undefined) =>
      value == null ? none : t("peopleTools.columns.hours", { hours: Number(value) }),
    percent: (value: string | null | undefined) =>
      value == null ? none : t("peopleTools.columns.percent", { value: Number(value) }),
  };
}

/** Selected row ids, kept across "Load more" pages. */
export function useSelection() {
  const [selected, setSelected] = useState<string[]>([]);
  return {
    selected,
    isSelected: (id: string) => selected.includes(id),
    toggle: (id: string) =>
      setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id])),
    setAll: (ids: string[], on: boolean) =>
      setSelected((s) =>
        on ? Array.from(new Set([...s, ...ids])) : s.filter((x) => !ids.includes(x)),
      ),
    clear: () => setSelected([]),
  };
}

/** A checkbox column: a labelled checkbox per row and "select all shown" in the header. */
export function selectionColumn<T>(
  selection: ReturnType<typeof useSelection>,
  rows: T[],
  getId: (row: T) => string,
  getName: (row: T) => string,
  labels: { all: string; row: (name: string) => string },
): ColumnDef<T, unknown> {
  const ids = rows.map(getId);
  const all = ids.length > 0 && ids.every((id) => selection.isSelected(id));
  return {
    id: "select",
    header: () => (
      <input
        type="checkbox"
        className="size-4"
        aria-label={labels.all}
        checked={all}
        onChange={(e) => selection.setAll(ids, e.target.checked)}
      />
    ),
    cell: ({ row }) => (
      <input
        type="checkbox"
        className="size-4"
        aria-label={labels.row(getName(row.original))}
        checked={selection.isSelected(getId(row.original))}
        onChange={() => selection.toggle(getId(row.original))}
      />
    ),
  };
}
