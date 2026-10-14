import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "./App";
import { mockApi } from "./test-utils";

/* E25 in the portal: a family's referral page and the partner (affiliate) portal. */

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const FAMILY = {
  role: "client",
  organisation: { name: "Bright Minds", primary_colour: "" },
  clients: [{ id: "c1", name: "The Patels" }],
  students: [{ id: "s1", name: "Arjun Patel" }],
  features: {
    cancellations: false, absence: false, invoices: false, reports: false, profile: false,
    booking: false, reschedule: false, classes: false, referrals: true,
  },
  welcome_text: "",
  help_url: "",
  terms_url: "",
}; // prettier-ignore

const GBP = (amount: string) => ({ amount, currency: "GBP" });

describe("referrals in the client portal", () => {
  it("shows the link, what friends get and the families referred", async () => {
    window.history.pushState(null, "", "/portal/referrals");
    mockApi({
      "GET /api/v1/portal/me": { body: FAMILY },
      "GET /api/v1/branding": { body: {} },
      "GET /api/v1/portal/referrals": {
        body: {
          code: "K7M2Q9XA",
          link: "https://brightminds.tutortrack.app/?ref=K7M2Q9XA",
          program: {
            name: "Refer a friend", referrer_reward: GBP("20.00"),
            referrer_reward_kind: "credit", milestone: "first_payment", milestone_lessons: 1,
            referee_discount_percent: "10.00", terms: "",
          },
          referrals: [
            { id: "r1", name: "The S.", status: "rewarded", created_at: "2026-09-01T10:00:00Z",
              rewarded_at: "2026-09-20T10:00:00Z", reward: GBP("20.00") },
          ],
          earned: [GBP("20.00")],
        },
      },
    }); // prettier-ignore
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Refer a friend" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Refer a friend" })).toBeInTheDocument();
    expect(
      screen.getByText("https://brightminds.tutortrack.app/?ref=K7M2Q9XA"),
    ).toBeInTheDocument();
    expect(screen.getByText(/you get £20.00 credit/)).toBeInTheDocument();
    expect(screen.getByText(/They get 10% off/)).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Families you referred" });
    expect(within(table).getByText("The S.")).toBeInTheDocument();
    expect(within(table).getByText("Rewarded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
  });
});

describe("the partner portal", () => {
  it("shows an affiliate their links, clients and statements", async () => {
    window.history.pushState(null, "", "/portal/affiliate");
    mockApi({
      "GET /api/v1/me": {
        body: { user: { id: "u9" }, membership: { id: "m9", role: "affiliate" } },
      },
      "GET /api/v1/branding": { body: {} },
      "GET /api/v1/portal/affiliate": {
        body: {
          name: "Hillside PTA", organisation: "Bright Minds", payout_method: "manual",
          bank_hint: "",
          summary: {
            clicks: 7, referred: 2, converted: 1,
            totals: [{ currency: "GBP", earned: GBP("20.00"), unpaid: GBP("20.00"),
                       paid: GBP("0.00") }],
          },
          links: [{ code: "HILL0001", name: "Newsletter", clicks: 7,
                    url: "https://brightminds.tutortrack.app/?ref=HILL0001" }],
        },
      },
      "GET /api/v1/portal/affiliate/clients": {
        body: [{ id: "a1", name: "The S.", attributed_at: "2026-09-01T10:00:00Z",
                 converted_at: "2026-09-10T10:00:00Z", commission: GBP("20.00") }],
      },
    }); // prettier-ignore
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Welcome, Hillside PTA" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Earned £20.00; £20.00 not yet paid.")).toBeInTheDocument();
    expect(screen.getByText("Newsletter · 7 visits")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Partner menu" });
    fireEvent.click(within(nav).getByRole("link", { name: "Referred clients" }));
    expect(await screen.findByRole("table", { name: "Referred clients" })).toBeInTheDocument();
    expect(screen.getByText("The S.")).toBeInTheDocument();
  });
});
