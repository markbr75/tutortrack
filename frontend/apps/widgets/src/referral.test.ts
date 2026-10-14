import { afterEach, describe, expect, it, vi } from "vitest";

import { captureReferral, referralCode } from "./referral";
import { mockFetch } from "./test-helpers";

const VALID = { valid: true, kind: "referral", landing_path: "/", remember_days: 90, offer: "10%" };

function clearCookies() {
  for (const name of ["tt_ref", "tt_consent"]) {
    document.cookie = `${name}=; max-age=0; path=/`;
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
  window.sessionStorage.clear();
  clearCookies();
});

describe("referral attribution (E25)", () => {
  it("counts the visit and keeps the code for the session without consent", async () => {
    window.history.pushState(null, "", "/?ref=k7m2q9xa");
    const calls = mockFetch({ "POST ref": VALID });
    expect(await captureReferral()).toEqual(VALID);
    expect(calls).toEqual([{ method: "POST", url: "ref", body: { code: "K7M2Q9XA" } }]);
    expect(document.cookie).not.toContain("tt_ref=");
    window.history.pushState(null, "", "/contact");
    expect(referralCode()).toBe("K7M2Q9XA");
  });

  it("remembers the code in a cookie with marketing consent", async () => {
    const consent = { necessary: true, analytics: false, marketing: true, version: 1 };
    document.cookie = `tt_consent=${encodeURIComponent(JSON.stringify(consent))}; path=/`;
    window.history.pushState(null, "", "/?ref=HILL0001");
    mockFetch({ "POST ref": VALID });
    await captureReferral();
    expect(document.cookie).toContain("tt_ref=HILL0001");
    window.sessionStorage.clear();
    window.history.pushState(null, "", "/");
    expect(referralCode()).toBe("HILL0001");
  });

  it("ignores pages without a code and malformed codes", async () => {
    const calls = mockFetch({});
    expect(await captureReferral()).toBeNull();
    window.history.pushState(null, "", "/?ref=<script>");
    expect(await captureReferral()).toBeNull();
    expect(calls).toEqual([]);
    expect(referralCode()).toBe("");
  });
});
