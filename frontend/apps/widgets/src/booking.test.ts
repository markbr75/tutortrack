import { afterEach, describe, expect, it, vi } from "vitest";

import "./index";

import { BRAND, mockFetch, settle } from "./test-helpers";

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

const soon = new Date(Date.now() + 2 * 86_400_000).toISOString();

describe("tt-booking", () => {
  it("picks a time, holds it for a new family and books", async () => {
    const calls = mockFetch({
      "GET branding": BRAND,
      "GET booking/services": [
        {
          id: "sv1",
          name: "Maths 1:1",
          description: "",
          duration_minutes: 60,
          price: { amount: "40.00", currency: "GBP" },
          tutors: [{ id: "t1", name: "Nia A." }],
        },
      ],
      "GET booking/slots": [{ tutor: "t1", tutor_name: "Nia A.", start: soon, end: soon }],
      "POST booking/holds": {
        id: "h1",
        status: "held",
        start: soon,
        tutor_name: "Nia A.",
        service_name: "Maths 1:1",
        expires_at: soon,
        quote: { amount: { amount: "40.00", currency: "GBP" } },
        token: "secret",
      },
      "POST booking/holds/h1/submit": {
        booking: { id: "h1", status: "confirmed", start: soon, tutor_name: "Nia A." },
        pay_url: "",
      },
    });
    const el = document.createElement("tt-booking");
    document.body.append(el);
    await settle(el);
    const root = el.shadowRoot!;
    expect(root.querySelector("label[for=tt-service]")?.textContent).toBe(
      "What would you like to book?",
    );
    const select = root.querySelector<HTMLSelectElement>("#tt-service")!;
    select.value = "sv1";
    select.dispatchEvent(new Event("change"));
    await settle(el);
    root.querySelector<HTMLButtonElement>("fieldset button")!.click();
    await settle(el);
    const form = root.querySelector("form")!;
    for (const [name, value] of Object.entries({
      first_name: "Sam",
      last_name: "Lee",
      email: "sam@example.com",
      student: "Kai",
    })) {
      form.querySelector<HTMLInputElement>(`[name=${name}]`)!.value = value;
    }
    form.dispatchEvent(new Event("submit"));
    await settle(el);
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      service: "sv1",
      tutor: "t1",
      contact: { first_name: "Sam", email: "sam@example.com", student_first_name: "Kai" },
    });
    root.querySelector<HTMLButtonElement>(".card button")!.click();
    await settle(el);
    expect(calls.some((c) => c.url === "booking/holds/h1/submit?token=secret")).toBe(true);
    expect(root.textContent).toContain("You're booked.");
  });
});
