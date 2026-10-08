import { describe, expect, it } from "vitest";

import { createI18n, formatDateTime, formatMoney } from "./index";

describe("i18n", () => {
  it("falls back to en-GB strings for en-US", () => {
    expect(createI18n("en-US").t("nav.home")).toBe("Home");
  });

  it("interpolates values", () => {
    expect(createI18n().t("errors.reference", { requestId: "abc" })).toBe("Reference: abc");
  });

  it("formats money per locale and currency", () => {
    expect(formatMoney({ amount: "1234.5", currency: "GBP" })).toBe("£1,234.50");
    expect(formatMoney({ amount: "1234.5", currency: "USD" }, "en-US")).toBe("$1,234.50");
  });

  it("formats datetimes in a given timezone", () => {
    const iso = "2025-07-03T15:00:00Z";
    expect(formatDateTime(iso, "en-GB", "Europe/London", { timeStyle: "short" })).toBe("16:00");
    expect(formatDateTime(iso, "en-US", "America/New_York", { timeStyle: "short" })).toBe(
      "11:00 AM",
    );
  });
});
