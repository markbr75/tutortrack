type Money = { amount: string; currency: string };

/** Adds decimal money strings exactly (no floats), per currency, keeping first-seen order. */
export function sumByCurrency(values: Money[]): Money[] {
  const totals = new Map<string, { units: bigint; places: number }>();
  for (const value of values) {
    const negative = value.amount.trim().startsWith("-");
    const [whole = "0", fraction = ""] = value.amount.replace("-", "").trim().split(".");
    const current = totals.get(value.currency) ?? { units: 0n, places: 0 };
    const places = Math.max(current.places, fraction.length);
    const scale = (units: bigint, from: number) => units * 10n ** BigInt(places - from);
    const units = BigInt(`${whole}${fraction}` || "0") * (negative ? -1n : 1n);
    totals.set(value.currency, {
      units: scale(current.units, current.places) + scale(units, fraction.length),
      places,
    });
  }
  return [...totals].map(([currency, { units, places }]) => {
    const negative = units < 0n;
    const digits = (negative ? -units : units).toString().padStart(places + 1, "0");
    const amount = places ? `${digits.slice(0, -places)}.${digits.slice(-places)}` : digits;
    return { amount: `${negative ? "-" : ""}${amount}`, currency };
  });
}
