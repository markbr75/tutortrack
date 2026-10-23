import { useRef, useState } from "react";

export type Value = string | number | boolean | null | undefined;

export type DetailField = {
  name: string;
  label: string;
  kind?: "text" | "email" | "tel" | "number" | "date" | "textarea" | "checkbox" | "select";
  /** For `select`: the choices; the "" value saves as empty (null). */
  options?: ReadonlyArray<{ value: string; label: string }>;
  autoComplete?: string;
  hint?: string;
  /** Takes the whole row (long text). */
  wide?: boolean;
};

/** Open/closed state for an in-place edit, returning focus to its Edit button on close. */
export function useEditing() {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  return {
    open,
    buttonRef,
    start: () => setOpen(true),
    stop: () => {
      setOpen(false);
      // Back to the button that opened the form (keyboard and screen-reader users).
      requestAnimationFrame(() => buttonRef.current?.focus());
    },
  };
}

const ADDRESS_KEYS = ["line1", "line2", "city", "postcode"] as const;
type Address = Partial<Record<(typeof ADDRESS_KEYS)[number] | "region" | "country", string>>;

/** Address lines as flat fields of a record, for `DetailsForm`. */
export function addressValues(address: Address | null | undefined): Record<string, string> {
  return Object.fromEntries(ADDRESS_KEYS.map((key) => [key, address?.[key] ?? ""]));
}

/** The address fields' labels, in postal order. */
export function addressFields(t: (key: string) => string): DetailField[] {
  return [
    { name: "line1", label: t("editDetails.line1"), autoComplete: "address-line1", wide: true },
    { name: "line2", label: t("editDetails.line2"), autoComplete: "address-line2", wide: true },
    { name: "city", label: t("editDetails.city"), autoComplete: "address-level2" },
    { name: "postcode", label: t("editDetails.postcode"), autoComplete: "postal-code" },
  ];
}

/** Moves changed address lines into `input` (the API replaces the whole address, so the
 * unchanged lines go too). */
export function withAddress(
  changes: Record<string, Value>,
  input: string,
  current: Address | null | undefined,
): Record<string, Value | Address> {
  const lines = ADDRESS_KEYS.filter((key) => key in changes);
  if (!lines.length) return changes;
  const rest = Object.fromEntries(
    Object.entries(changes).filter(([key]) => !(ADDRESS_KEYS as readonly string[]).includes(key)),
  );
  const address: Address = {
    region: current?.region ?? "",
    country: current?.country ?? "",
    ...addressValues(current),
    ...Object.fromEntries(lines.map((key) => [key, String(changes[key] ?? "")])),
  };
  return { ...rest, [input]: address };
}
