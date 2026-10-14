import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "./App";
import { mockApi } from "./test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

function tutor(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { membership: { role: "tutor" }, user: { email: "n@x.com" } } },
    "GET /api/v1/tutor/me": {
      body: { id: "t1", name: "Nia", email: "n@x.com", can_cancel: true,
              can_edit_lessons: false, can_see_pay: true },
    }, // prettier-ignore
    ...extra,
  };
}

const REVIEW = {
  id: "r1", invoice_run: "run1", tutor: "t1", tutor_name: "Nia", status: "pending", comment: "",
  flagged_invoices: [], decided_at: null, period_start: "2026-09-01", period_end: "2026-09-30",
  review_until: "2026-10-16T09:00:00Z",
  lessons: [{ invoice_id: "i1", date: "2026-09-08", lesson_id: "l1", description: "GCSE Maths",
              student: "Arjun Patel", duration_minutes: 60 }],
}; // prettier-ignore

describe("G3: tutors check their lessons before invoices go out", () => {
  it("lists lessons without amounts and reports a problem", async () => {
    window.history.pushState(null, "", "/portal/tutor/invoice-review");
    const calls = mockApi(
      tutor({
        "GET /api/v1/me/invoice-reviews": { body: { next: null, previous: null, results: [REVIEW] } },
        "POST /api/v1/me/invoice-reviews/r1/flag": { body: { ...REVIEW, status: "flagged" } },
      }),
    ); // prettier-ignore
    render(<App />);
    expect(await screen.findByText("Arjun Patel")).toBeInTheDocument();
    expect(screen.queryByText(/£/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Something's wrong" }));
    fireEvent.change(screen.getByLabelText("What's wrong?"), {
      target: { value: "It was 45 minutes" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        comment: "It was 45 minutes",
      }),
    );
  });

  it("shows the annual earnings summary with a PDF link", async () => {
    window.history.pushState(null, "", "/portal/tutor/earnings");
    const gbp = (amount: string) => ({ amount, currency: "GBP" });
    mockApi(
      tutor({
        "GET /api/v1/me/earnings": {
          body: { upcoming: [], upcoming_total: {}, held: [], held_total: {}, payouts: [],
                  statements: [], year_to_date: {} },
        },
        "GET /api/v1/me/earnings/annual": {
          body: { year: 2026, basis: "tax_year", start: "2026-04-06", end: "2027-04-05",
                  currencies: [{ currency: "GBP", earnings: gbp("1200.00"), reimbursements: gbp("30.00"),
                                 total: gbp("1230.00"), by_kind: [], by_month: [], payouts: 4 }] },
        },
      }),
    ); // prettier-ignore
    render(<App />);
    expect(await screen.findByText("Earnings summary")).toBeInTheDocument();
    expect(await screen.findByText(/Tax year/)).toBeInTheDocument();
    expect(screen.getByText("£1,230.00")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "href",
      expect.stringContaining("/api/v1/me/earnings/annual?year="),
    );
  });
});
