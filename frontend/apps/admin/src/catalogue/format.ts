export const PAGE = { page_size: 200 } as const;

export interface MoneyValue {
  amount: string;
  currency: string;
}

/** Shows a 4-decimal rate as money in the viewer's locale ("£40.00"). */
export function formatRate(value: MoneyValue | null | undefined, locale: string): string {
  if (!value) return "";
  return new Intl.NumberFormat(locale, { style: "currency", currency: value.currency }).format(
    Number(value.amount),
  );
}
