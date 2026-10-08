import { describe, expect, it } from "vitest";

import "./powered-by";

describe("tt-powered-by", () => {
  it("renders inside its shadow root", async () => {
    const el = document.createElement("tt-powered-by");
    el.org = "Bright Minds";
    document.body.append(el);
    await el.updateComplete;
    expect(el.shadowRoot?.textContent).toContain("Bright Minds · Powered by");
  });
});
