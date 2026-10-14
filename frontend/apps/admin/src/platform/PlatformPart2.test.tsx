import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const STAFF = {
  email: "pat@tutortrack.app",
  is_platform_staff: true,
  mfa_verified: true,
  network_allowed: true,
};

const gbp = (amount: string) => ({ amount, currency: "GBP" });

const MONTH = {
  month: "2026-10-14",
  mrr: gbp("1250.00"), arr: gbp("15000.00"), customers: 25, arpa: gbp("50.00"), trialing: 8,
  past_due_mrr: gbp("49.00"), new_mrr: gbp("98.00"), reactivation_mrr: gbp("0.00"),
  expansion_mrr: gbp("30.00"), contraction_mrr: gbp("0.00"), churned_mrr: gbp("49.00"),
  net_new_mrr: gbp("79.00"), new_customers: 2, churned_customers: 1,
  logo_churn_rate: "0.0417", revenue_churn_rate: "0.0418", net_revenue_retention: "0.9838",
}; // prettier-ignore

function console_(extra: Routes): Routes {
  return { "GET /api/v1/platform/me": { body: STAFF }, ...extra };
}

describe("platform console part 2", () => {
  it("lists organisations by health and starts a recalculation", async () => {
    window.history.pushState(null, "", "/platform/health");
    const calls = mockApi(
      console_({
        "GET /api/v1/platform/health": {
          body: {
            results: [
              {
                id: "o1", name: "Bright Minds", slug: "brightminds", status: "active",
                plan: "team", last_activity: null, score: 32, risk: "at_risk",
                scored_on: "2026-10-14",
                components: { usage: 20, tutors: 0, payments: null, reliability: 100, support: 75, nps: null },
              },
            ],
            next: null,
            previous: null,
          },
        },
        "GET /api/v1/platform/health/risk-counts": { body: { healthy: 4, watch: 2, at_risk: 1 } },
        "POST /api/v1/platform/insights/run": { status: 202, body: { workflow_id: "w1" } },
      }),
    ); // prettier-ignore
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Tenant health" })).toBeInTheDocument();
    const row = (await screen.findByRole("link", { name: "Bright Minds" })).closest("tr")!;
    expect(within(row).getByText("32")).toBeInTheDocument();
    expect(within(row).getByText("At risk")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Recalculate now" }));
    expect(await screen.findByText(/Recalculation started/)).toBeInTheDocument();
    expect(
      calls.some((c) => c.method === "POST" && c.path === "/api/v1/platform/insights/run"),
    ).toBe(true);
  });

  it("shows SaaS metrics for a currency", async () => {
    window.history.pushState(null, "", "/platform/metrics");
    mockApi(
      console_({
        "GET /api/v1/platform/saas-metrics": {
          body: {
            currency: "GBP",
            currencies: ["GBP", "USD"],
            months: [MONTH],
            trial_conversion: [
              { month: "2026-09-01", trials: 10, converted: 3, conversion_rate: "0.3000" },
            ],
            cohorts: [
              {
                month: "2026-09-01",
                size: 4,
                starting_mrr: gbp("200.00"),
                logo_retention: ["1.0000", "0.7500"],
                revenue_retention: ["1.0000", "0.9000"],
              },
            ],
          },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: "SaaS metrics" })).toBeInTheDocument();
    const mrr = (await screen.findByText("MRR", { selector: "dt" })).parentElement!;
    expect(within(mrr).getByText("£1,250.00")).toBeInTheDocument();
    expect(screen.getByText("£15,000.00")).toBeInTheDocument();
    expect(screen.getAllByText("98.4%")).toHaveLength(2); // tile and table
    expect(screen.getByRole("heading", { name: "Trial conversion by sign-up month" }));
    expect(screen.getByText("30%")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument();
  });

  it("answers a support conversation", async () => {
    window.history.pushState(null, "", "/platform/support/c1");
    const conversation = {
      id: "c1", organisation_id: "o1", organisation_name: "Bright Minds", subject: "Invoices",
      status: "open", page: "/billing", opened_by_name: "Sam", assignee_name: "",
      support_unread: true, last_message_at: "2026-10-14T10:00:00Z",
      created_at: "2026-10-14T10:00:00Z",
      messages: [{ id: "m1", from_support: false, author_name: "Sam", body: "How?", created_at: "2026-10-14T10:00:00Z" }],
    }; // prettier-ignore
    const calls = mockApi(
      console_({
        "GET /api/v1/platform/support/c1": { body: conversation },
        "POST /api/v1/platform/support/c1/reply": {
          status: 201,
          body: {
            ...conversation,
            status: "answered",
            messages: [
              ...conversation.messages,
              { id: "m2", from_support: true, author_name: "Pat", body: "Like this.", created_at: "2026-10-14T10:05:00Z" },
            ],
          },
        },
      }),
    ); // prettier-ignore
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Invoices" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Reply"), { target: { value: "Like this." } });
    fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    expect(await screen.findByText("Like this.")).toBeInTheDocument();
    expect(calls.find((c) => c.path.endsWith("/reply"))?.body).toEqual({ body: "Like this." });
  });

  it("shows NPS and product usage", async () => {
    window.history.pushState(null, "", "/platform/feedback");
    mockApi(
      console_({
        "GET /api/v1/platform/nps": {
          body: {
            days: 90, nps: 33, answers: 3, dismissed: 1, promoters: 2, passives: 0, detractors: 1,
            by_plan: [{ plan: "team", nps: 33, answers: 3 }],
            by_month: [{ month: "2026-10-01", nps: 33, answers: 3 }],
            comments: [{ organisation_id: "o1", organisation: "Bright Minds", score: 10, role: "owner", comment: "Love it", created_at: "2026-10-10T10:00:00Z" }],
            csat_average: "4.50", csat_answers: 2,
          },
        },
        "GET /api/v1/platform/usage": {
          body: {
            days: 30, events: 12, people: 3, organisations: 2,
            top_events: [{ name: "page.viewed", count: 10, organisations: 2, people: 3 }],
            top_pages: [{ route: "/billing", count: 6, people: 2 }],
            daily: [],
            funnel: [{ step: "signed_up", organisations: 10 }, { step: "service", organisations: 5 }],
          },
        },
      }),
    ); // prettier-ignore
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Feedback and usage" })).toBeInTheDocument();
    expect(await screen.findByText("Love it")).toBeInTheDocument();
    expect(screen.getByText("4.50")).toBeInTheDocument();
    expect(await screen.findByText("page.viewed")).toBeInTheDocument();
    expect(screen.getByText("Set up a service")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
  });
});
