import { afterEach, beforeEach, describe, expect, it } from "vitest";

import "./cookie-consent";

import { readChoice } from "./cookie-consent";

beforeEach(() => {
  document.cookie = "tt_consent=; Max-Age=0; Path=/";
  document.body.innerHTML = "";
});

describe("tt-cookie-consent", () => {
  it("records a rejection and hides itself", async () => {
    const el = document.createElement("tt-cookie-consent");
    document.body.appendChild(el);
    await el.updateComplete;
    const buttons = el.shadowRoot!.querySelectorAll("button");
    expect(buttons).toHaveLength(2);
    const events: CustomEvent[] = [];
    window.addEventListener("tt-cookie-consent", (e) => events.push(e as CustomEvent));
    buttons[1]!.click();
    await el.updateComplete;
    expect(readChoice()).toMatchObject({ analytics: false, marketing: false });
    expect(events[0]!.detail.analytics).toBe(false);
    expect(el.shadowRoot!.querySelector("section")).toBeNull();
  });
});

describe("tt-cookie-consent text", () => {
  afterEach(() => {
    document.documentElement.lang = "";
    delete window.TutorTrackWidgets;
  });

  async function texts(setup?: (el: HTMLElement) => void) {
    const el = document.createElement("tt-cookie-consent");
    setup?.(el);
    document.body.appendChild(el);
    await el.updateComplete;
    const root = el.shadowRoot!;
    return {
      region: root.querySelector("section")!.getAttribute("aria-label"),
      buttons: [...root.querySelectorAll("button")].map((b) => b.textContent!.trim()),
    };
  }

  it("uses the translated defaults for the page's language", async () => {
    document.documentElement.lang = "en-us";
    expect(await texts()).toEqual({
      region: "Cookies",
      buttons: ["Accept all", "Reject non-essential"],
    });
  });

  it("still takes the page's own wording from attributes or messages", async () => {
    window.TutorTrackWidgets = { messages: { cookieAccept: "Allow all" } };
    const result = await texts((el) => {
      el.setAttribute("heading", "Cookies on this site");
      el.setAttribute("reject-label", "Only necessary");
    });
    expect(result).toEqual({
      region: "Cookies on this site",
      buttons: ["Allow all", "Only necessary"],
    });
  });
});
