import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const gbp = (amount: string) => ({ amount, currency: "GBP" });

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { membership: { role: "tutor" }, user: { email: "n@x.com" } } },
    "GET /api/v1/tutor/me": {
      body: { id: "t1", name: "Nia", email: "n@x.com", can_cancel: true,
              can_edit_lessons: false, can_see_pay: true },
    }, // prettier-ignore
    ...extra,
  };
}

const ITEM = {
  id: "i1", tutor: "t1", tutor_name: "Nia", kind: "lesson", status: "held",
  description: "GCSE Maths · 2026-10-08", date: "2026-10-08", quantity: "1.00", unit: "hour",
  amount: gbp("25.00"), hold_reasons: ["report_overdue"], hold_note: "", lesson: "l1",
  pay_run: null, pay_run_number: null, expense: null, created_at: "2026-10-08T10:00:00Z",
}; // prettier-ignore

describe("tutor pay", () => {
  it("shows held pay with what releases it, and statements", async () => {
    window.history.pushState(null, "", "/portal/tutor/earnings");
    mockApi(
      routes({
        "GET /api/v1/me/earnings": {
          body: {
            upcoming: [{ ...ITEM, id: "i2", status: "ready", hold_reasons: [] }],
            upcoming_total: { GBP: "25.00" },
            held: [ITEM],
            held_total: { GBP: "25.00" },
            payouts: [],
            statements: [
              {
                id: "s1", tutor: "t1", tutor_name: "Nia", kind: "self_billing",
                number: "SB-ABC123-0001", issued_at: "2026-10-01T10:00:00Z", net: gbp("100.00"),
                vat: gbp("0.00"), total: gbp("100.00"), pay_run_number: "PR-000001",
              },
            ],
            year_to_date: { GBP: "1200.00" },
          },
        }, // prettier-ignore
      }),
    );
    render(<App />);
    expect(await screen.findByText("Write the lesson report to release this.")).toBeInTheDocument();
    expect(screen.getByText("£1,200.00")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Self-billing invoice SB-ABC123-0001/ }),
    ).toHaveAttribute("href", "/api/v1/pay-statements/s1/pdf");
  });

  it("claims mileage with suggested distance", async () => {
    window.history.pushState(null, "", "/portal/tutor/expenses");
    const calls = mockApi(
      routes({
        "GET /api/v1/expense-categories": {
          body: [{ id: "c1", name: "Mileage", kind: "mileage", distance_unit: "mi" }],
        },
        "GET /api/v1/expenses": { body: { results: [], next: null, previous: null } },
        "GET /api/v1/expenses/mileage-suggestions": {
          body: [{ origin: "Patels", destination: "Smiths", lesson: "l2", distance: "4.2",
                   unit: "mi" }],
        }, // prettier-ignore
        "POST /api/v1/expenses": { status: 201, body: { id: "e1" } },
      }),
    );
    render(<App />);
    await screen.findByRole("option", { name: "Mileage" });
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "c1" } });
    fireEvent.click(await screen.findByRole("button", { name: "Suggest from my lessons" }));
    await vi.waitFor(() => expect(screen.getByLabelText("Distance (mi)")).toHaveValue("4.2"));
    fireEvent.click(screen.getByRole("button", { name: "Send claim" }));
    expect(await screen.findByText("Claim sent for approval.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      category: "c1",
      distance: "4.2",
      amount: null,
      description: "Patels → Smiths",
    });
  });
});
