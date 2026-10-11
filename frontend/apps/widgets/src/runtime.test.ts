import { afterEach, describe, expect, it, vi } from "vitest";

import { apiBase, applyTheme, emit } from "./runtime";
import { BRAND } from "./test-helpers";

afterEach(() => {
  document.head.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("widget runtime", () => {
  it("finds the API from the loader script", () => {
    document.head.innerHTML =
      '<script data-org="brightminds" data-api="https://portal.bm.co.uk/"></script>';
    expect(apiBase()).toBe("https://portal.bm.co.uk");
    document.head.innerHTML = '<script data-org="brightminds"></script>';
    expect(apiBase()).toBe("https://brightminds.tutortrack.app");
    document.head.innerHTML = '<script data-org="brightminds" data-api=""></script>';
    expect(apiBase()).toBe("");
  });

  it("applies the brand and only --tt-* theme properties", () => {
    const host = document.createElement("div");
    applyTheme(host, BRAND, { "--tt-radius": "12px", color: "red" });
    expect(host.style.getPropertyValue("--tt-brand-color")).toBe("#1d4ed8");
    expect(host.style.getPropertyValue("--tt-radius")).toBe("12px");
    expect(host.style.getPropertyValue("color")).toBe("");
  });

  it("emits analytics events to window, GA4, GTM and the Meta pixel", () => {
    const gtag = vi.fn();
    const fbq = vi.fn();
    vi.stubGlobal("gtag", gtag);
    vi.stubGlobal("fbq", fbq);
    window.dataLayer = [];
    const seen: unknown[] = [];
    window.addEventListener("tt:enquiry_submitted", (e) => seen.push((e as CustomEvent).detail));
    emit("enquiry_submitted", { form: "enquire" });
    expect(seen).toEqual([{ form: "enquire" }]);
    expect(gtag).toHaveBeenCalledWith("event", "generate_lead", { form: "enquire" });
    expect(fbq).toHaveBeenCalledWith("track", "Lead", { form: "enquire" });
    expect(window.dataLayer).toEqual([{ event: "tt_enquiry_submitted", form: "enquire" }]);
  });
});
