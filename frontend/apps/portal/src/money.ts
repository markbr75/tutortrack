/** Adds decimal amounts exactly (money is never a float): scales to whole minor units. */
export function sumAmounts(amounts: ReadonlyArray<string>): string {
  const scale = Math.max(0, ...amounts.map((a) => (a.split(".")[1] ?? "").length));
  const whole = (a: string) => {
    const [int = "0", frac = ""] = a.replace(/^-/, "").split(".");
    const units = BigInt((int || "0") + frac.padEnd(scale, "0"));
    return a.startsWith("-") ? -units : units;
  };
  const total = amounts.reduce((sum, a) => sum + whole(a), 0n);
  const sign = total < 0n ? "-" : "";
  const digits = (total < 0n ? -total : total).toString().padStart(scale + 1, "0");
  return scale ? `${sign}${digits.slice(0, -scale)}.${digits.slice(-scale)}` : `${sign}${digits}`;
}

/** True when a decimal amount is above zero. */
export function isPositive(amount: string | undefined | null): boolean {
  return Boolean(amount) && /[1-9]/.test(amount!) && !amount!.startsWith("-");
}
