import { beforeEach, describe, expect, it } from "vitest";

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
