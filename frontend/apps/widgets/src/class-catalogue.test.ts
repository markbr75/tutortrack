import { afterEach, describe, expect, it, vi } from "vitest";

import "./index";

import { BRAND, mockFetch, settle } from "./test-helpers";

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

function cls(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    name: "Saturday 10am",
    course: { id: "co1", name: "Year 6 11+ Prep", description: "", subject: "", image_url: "" },
    term: "Autumn",
    start_date: "2026-10-17",
    weekdays: [5],
    start_time: "10:00",
    location: "Centre",
    online: false,
    min_age: 9,
    max_age: 11,
    year_groups: [],
    pricing_label: "Per term",
    price: "£120.00",
    places_left: 3,
    full: false,
    waitlist: false,
    ...overrides,
  };
}

describe("tt-class-catalogue", () => {
  it("filters by age and enrols a new family", async () => {
    const calls = mockFetch({
      "GET branding": BRAND,
      "GET catalogue": {
        classes: [cls("g1"), cls("g2", { name: "Sunday", min_age: 14, max_age: 16 })],
        terms: "",
        payment: "none",
      },
      "POST enrol": {
        status: "enrolled",
        pay_url: "",
        student: "Tobi",
        waitlist_position: null,
      },
    });
    const el = document.createElement("tt-class-catalogue");
    document.body.append(el);
    await settle(el);
    const root = el.shadowRoot!;
    expect(root.querySelectorAll("li.card")).toHaveLength(2);
    expect(root.textContent).toContain("3 places left");
    const age = root.querySelector<HTMLInputElement>("#tt-c-age")!;
    age.value = "10";
    age.dispatchEvent(new Event("input"));
    await settle(el);
    expect(root.querySelectorAll("li.card")).toHaveLength(1);
    root.querySelector<HTMLButtonElement>("li.card button")!.click();
    await settle(el);
    const form = root.querySelector("form")!;
    for (const [name, value] of Object.entries({
      first_name: "Sam",
      last_name: "Okafor",
      email: "sam@example.com",
      student: "Tobi",
      date_of_birth: "2016-03-01",
    })) {
      form.querySelector<HTMLInputElement>(`[name=${name}]`)!.value = value;
    }
    form.dispatchEvent(new SubmitEvent("submit", { cancelable: true }));
    await settle(el);
    expect(root.querySelector("[role=status]")?.textContent).toContain("Tobi is enrolled");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({
      group_class: "g1",
      join_waitlist: false,
      contact: { first_name: "Sam", email: "sam@example.com" },
      student: { first_name: "Tobi", date_of_birth: "2016-03-01" },
    });
  });

  it("offers the waitlist for a full class", async () => {
    mockFetch({
      "GET branding": BRAND,
      "GET catalogue": {
        classes: [cls("g1", { full: true, waitlist: true, places_left: 0 })],
        terms: "",
        payment: "none",
      },
    });
    const el = document.createElement("tt-class-catalogue");
    document.body.append(el);
    await settle(el);
    const button = el.shadowRoot!.querySelector<HTMLButtonElement>("li.card button")!;
    expect(button.getAttribute("aria-label")).toBe("Join the waitlist for Year 6 11+ Prep");
    expect(el.shadowRoot!.textContent).toContain("Full");
  });
});
