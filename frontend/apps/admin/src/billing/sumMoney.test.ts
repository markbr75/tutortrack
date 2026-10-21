import { sumByCurrency } from "./sumMoney";

describe("sumByCurrency", () => {
  it("adds decimal strings exactly, per currency, in first-seen order", () => {
    expect(
      sumByCurrency([
        { amount: "0.10", currency: "GBP" },
        { amount: "0.20", currency: "GBP" },
        { amount: "5", currency: "JPY" },
        { amount: "115.00", currency: "GBP" },
        { amount: "-0.30", currency: "GBP" },
      ]),
    ).toEqual([
      { amount: "115.00", currency: "GBP" },
      { amount: "5", currency: "JPY" },
    ]);
  });

  it("keeps a negative total and an empty list", () => {
    expect(sumByCurrency([{ amount: "-1.5", currency: "GBP" }])).toEqual([
      { amount: "-1.5", currency: "GBP" },
    ]);
    expect(sumByCurrency([])).toEqual([]);
  });
});
