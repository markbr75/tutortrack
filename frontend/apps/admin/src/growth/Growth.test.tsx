import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const STAFF = {
  ...ME,
  membership: { ...ME.membership, role: "coordinator" },
  permissions: {
    ...ME.permissions,
    "growth.review.view": "all",
    "growth.review.manage": "all",
    "growth.referral.view": "all",
    "growth.referral.manage": "all",
    "growth.affiliate.view": "all",
  },
};

const page = (results: unknown[]) => ({ body: { results, next: null, previous: null } });

const REVIEW = {
  id: "r1", client: "c1", client_name: "The Patels", contact: null, student: null,
  tutor: "t1", tutor_name: "Nia", rating: 5, criteria: {}, text: "Brilliant tutor.",
  reviewer_name: "Priya", publish_consent: true, source: "request", status: "pending",
  moderated_at: null, response: "", responded_at: null, google_prompted: true,
  published_as_testimonial: false, request: "q1", created_at: "2026-10-01T10:00:00Z",
}; // prettier-ignore

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: STAFF },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    ...extra,
  };
}

describe("reviews, referrals and affiliates", () => {
  it("moderates the review queue", async () => {
    window.history.pushState(null, "", "/growth");
    const calls = mockApi(
      routes({
        "GET /api/v1/reviews/summary": {
          body: { average: 4.5, count: 2, stars: { "1": 0, "2": 0, "3": 0, "4": 1, "5": 1 } },
        },
        "GET /api/v1/reviews": page([REVIEW]),
        "POST /api/v1/reviews/r1/approve": { body: { ...REVIEW, status: "approved" } },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Brilliant tutor.")).toBeInTheDocument();
    expect(screen.getByText("4.5 average from 2 approved reviews")).toBeInTheDocument();
    expect(screen.getByText("5 stars out of 5")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Reviews & referrals" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await vi.waitFor(() =>
      expect(
        calls.some((c) => c.method === "POST" && c.path === "/api/v1/reviews/r1/approve"),
      ).toBe(true),
    );
  });

  it("shows referrals with fraud flags and rewards one anyway", async () => {
    window.history.pushState(null, "", "/growth");
    const referral = {
      id: "f1", program: "p1", referrer: "c1", referrer_name: "The Patels", referee: "c2",
      referee_name: "The Smiths", code_value: "K7M2Q9XA", source: "link", status: "blocked",
      deadline: "2027-03-01T10:00:00Z", converted_at: "2026-10-02T10:00:00Z", rewarded_at: null,
      fraud_flags: ["same_email"], referrer_credit: null, referee_discount_id: "", note: "",
      enquiry_id: "", workflow_id: "referral:o1:f1", created_at: "2026-10-01T10:00:00Z",
    }; // prettier-ignore
    const calls = mockApi(
      routes({
        "GET /api/v1/reviews/summary": { body: { average: null, count: 0, stars: {} } },
        "GET /api/v1/reviews": page([]),
        "GET /api/v1/referral-programs": page([]),
        "GET /api/v1/referrals": page([referral]),
        "POST /api/v1/referrals/f1/approve": { body: { ...referral, status: "rewarded" } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Referrals" }));
    const table = await screen.findByRole("table", { name: "Referrals" });
    expect(within(table).getByText("Same email address")).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "Referral programme" })).toBeInTheDocument();
    fireEvent.click(within(table).getByRole("button", { name: "Reward anyway" }));
    await vi.waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/referrals/f1/approve")).toBe(true),
    );
  });
});

describe("the public review page", () => {
  it("collects stars, a comment and consent, then offers Google", async () => {
    window.history.pushState(null, "", "/review/tok123");
    const calls = mockApi({
      "GET /api/v1/public/review/tok123": {
        body: {
          organisation: "Bright Minds", tutor: "Nia", student: "Arjun", reviewer_name: "Priya",
          criteria: ["communication"], open: true, status: "pending",
        },
      },
      "POST /api/v1/public/review/tok123": {
        status: 201,
        body: { status: "submitted", google_review_url: "https://g.page/r/bm/review" },
      },
    }); // prettier-ignore
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "How are lessons with Nia going?" }),
    ).toBeInTheDocument();
    const overall = screen.getByRole("group", { name: "Overall rating" });
    fireEvent.click(within(overall).getByLabelText("5 stars out of 5"));
    fireEvent.change(screen.getByLabelText("Tell us more (optional)"), {
      target: { value: "Great lessons" },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Send review" }));
    expect(await screen.findByRole("heading", { name: "Thank you!" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Would you also review us on Google?" }),
    ).toHaveAttribute("href", "https://g.page/r/bm/review");
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      rating: 5,
      criteria: {},
      text: "Great lessons",
      reviewer_name: "Priya",
      publish_consent: true,
    });
  });
});
