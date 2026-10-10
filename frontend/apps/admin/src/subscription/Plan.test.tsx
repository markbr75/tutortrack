import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const OWNER = {
  ...ME,
  membership: { ...ME.membership, role: "owner" },
  permissions: {
    ...ME.permissions,
    "subscription.view": "all",
    "subscription.manage": "all",
    "org.settings.manage": "all",
  },
  features: { multi_branch: true },
};

const SUB = {
  plan: "solo",
  plan_name: "Solo",
  effective_plan: "agency",
  status: "trialing",
  interval: "month",
  currency: "GBP",
  trial_ends_at: new Date(Date.now() + 5 * 86_400_000).toISOString(),
  current_period_end: null,
  pending_plan: null,
  pending_interval: "",
  cancel_at_period_end: false,
  past_due_since: null,
  has_payment_method: false,
  card: null,
  can_manage: true,
};

const price = (component: string, unit_amount: string, included_quantity = 0) => ({
  interval: "month",
  component,
  unit_amount,
  included_quantity,
});

const PLANS = [
  {
    key: "solo", name: "Solo", description: "For one tutor.", visibility: "public", rank: 10,
    currency: "GBP", prices: [price("base_fee", "19")], features: {},
    limits: { max_tutors: 1 },
  },
  {
    key: "team", name: "Team", description: "For 2 to 15 tutors.", visibility: "public",
    rank: 20, currency: "GBP",
    prices: [price("base_fee", "39"), price("active_tutor", "6", 2)],
    features: {}, limits: { max_tutors: 15 },
  },
]; // prettier-ignore

const USAGE = {
  limits: [{ key: "max_tutors", title: "Tutors", used: 1, allowed: 1 }],
  billable_tutors: 1,
  included_tutors: 0,
  next_invoice: null,
  credits: [
    {
      credit_type: "sms", balance: 50, allowance: 50, included_balance: 50,
      purchased_balance: 0, used_this_period: 0, auto_top_up: false, top_up_pack: 500,
      low_threshold: 20, allow_overage: false, packs: [500, 2000],
    },
  ],
}; // prettier-ignore

const ENTITLEMENTS = {
  plan: "solo",
  status: "active",
  features: { multi_branch: false },
  limits: {},
  required_plans: { multi_branch: "agency" },
};

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: OWNER },
    "GET /api/v1/organisation": { body: { status: "trial", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/subscription": { body: SUB },
    "GET /api/v1/subscription/usage": { body: USAGE },
    "GET /api/v1/subscription/plans": { body: PLANS },
    "GET /api/v1/subscription/invoices": { body: [] },
    "GET /api/v1/entitlements": { body: ENTITLEMENTS },
    ...extra,
  };
}

describe("billing & plan", () => {
  it("shows the trial and usage, and upgrades after a preview", async () => {
    window.history.pushState(null, "", "/settings/plan");
    const calls = mockApi(
      routes({
        "POST /api/v1/subscription/change-plan": (_body, url) =>
          url.searchParams.get("preview")
            ? {
                status: 202,
                body: {
                  plan: "team", interval: "month", direction: "upgrade", effective: "now",
                  blockers: [], amount_due_now: null,
                },
              } // prettier-ignore
            : { body: { ...SUB, plan: "team", plan_name: "Team" } },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: /Your plan: Solo/ })).toBeInTheDocument();
    expect(screen.getByText(/5 days of your free trial left/)).toBeInTheDocument();
    expect(await screen.findByText("1 of 1")).toBeInTheDocument();
    expect(screen.getByText(/£6.00 a month per tutor after 2/)).toBeInTheDocument();
    // The banner nudges before the trial ends.
    expect(screen.getByText("Your free trial ends in 5 days.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Choose Team" }));
    const confirm = await screen.findByRole("region", { name: "Change plan" });
    expect(within(confirm).getByText("The change applies straight away.")).toBeInTheDocument();
    fireEvent.click(within(confirm).getByRole("button", { name: "Confirm" }));
    await vi.waitFor(() =>
      expect(calls.filter((c) => c.path.endsWith("/change-plan")).map((c) => c.search)).toEqual([
        "?preview=true",
        "",
      ]),
    );
  });

  it("lists what blocks a downgrade", async () => {
    window.history.pushState(null, "", "/settings/plan");
    mockApi(
      routes({
        "GET /api/v1/subscription": { body: { ...SUB, plan: "team", plan_name: "Team" } },
        "POST /api/v1/subscription/change-plan": {
          status: 202,
          body: {
            plan: "solo", interval: "month", direction: "downgrade", effective: "period_end",
            blockers: ["You have 3 tutors; Solo allows 1. Deactivate or archive 2 first."],
            amount_due_now: null,
          },
        }, // prettier-ignore
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Choose Solo" }));
    expect(await screen.findByText(/You have 3 tutors/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  });

  it("records the plan when Checkout returns", async () => {
    window.history.pushState(null, "", "/settings/plan?checkout=cs_1");
    const calls = mockApi(
      routes({
        "POST /api/v1/subscription/checkout-session/complete": {
          body: { ...SUB, has_payment_method: true },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Thank you. Your plan is set up.")).toBeInTheDocument();
    expect(calls.find((c) => c.path.endsWith("/complete"))?.body).toEqual({ session_id: "cs_1" });
    expect(window.location.search).toBe("");
  });

  it("buys credits", async () => {
    window.history.pushState(null, "", "/settings/plan");
    const calls = mockApi(
      routes({
        "POST /api/v1/subscription/credits/sms/top-up": {
          body: { status: "paid", url: "", account: USAGE.credits[0] },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Buy 500" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/top-up"))?.body).toEqual({ credits: 500 }),
    );
  });

  it("shows a locked feature with an upgrade link", async () => {
    window.history.pushState(null, "", "/settings");
    mockApi(routes({ "GET /api/v1/branches": { body: { results: [], next: null } } }));
    render(<App />);
    expect(await screen.findByText("Available on Agency and above.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See plans" })).toHaveAttribute(
      "href",
      "/settings/plan",
    );
  });

  it("opens the upgrade dialog when an action hits a plan limit", async () => {
    window.history.pushState(null, "", "/settings");
    mockApi(
      routes({
        "GET /api/v1/entitlements": {
          body: { ...ENTITLEMENTS, features: { multi_branch: true } },
        },
        "GET /api/v1/branches": { body: { results: [], next: null } },
        "POST /api/v1/branches": {
          status: 403,
          body: {
            type: "https://docs.tutortrack.app/problems/upgrade-required",
            title: "Your plan doesn't include this",
            status: 403,
            detail: "Your plan allows 1. Upgrade to add more.",
            limit: "max_branches",
            allowed: 1,
            used: 1,
            required_plan: "agency",
          },
        },
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Branch name"), { target: { value: "North" } });
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "N" } });
    fireEvent.click(screen.getByRole("button", { name: "Add branch" }));
    expect(await screen.findByRole("heading", { name: "Upgrade to Agency" })).toBeInTheDocument();
    expect(
      screen.getByText("Your plan allows 1 branches. Upgrade to add more."),
    ).toBeInTheDocument();
  });

  it("warns when a payment failed", async () => {
    mockApi(
      routes({
        "GET /api/v1/subscription": { body: { ...SUB, status: "past_due" } },
        "GET /api/v1/dashboard": { body: {} },
      }),
    );
    render(<App />);
    expect(await screen.findByText(/Your TutorTrack payment failed/)).toBeInTheDocument();
  });
});
