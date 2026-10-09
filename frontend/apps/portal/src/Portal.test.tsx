import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "./App";
import { mockApi } from "./test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const gbp = (amount: string) => ({ amount, currency: "GBP" });
const soon = new Date(Date.now() + 26 * 3600_000).toISOString();
const later = new Date(Date.now() + 27 * 3600_000).toISOString();

const LESSON = {
  id: "l1",
  title: "Maths group",
  start: soon,
  end: later,
  timezone: "Europe/London",
  status: "planned",
  online: false,
  meeting_url: "",
  location: "Centre",
  notes_for_client: "",
  tutors: [{ name: "Nia Adeyemi", email: "", phone: "" }],
  students: [
    { id: "s1", name: "Arjun Patel", outcome: "" },
    { id: "s2", name: "Maya Patel", outcome: "" },
  ],
};

function me(role: "client" | "student" = "client") {
  return {
    role,
    organisation: { name: "Bright Minds", primary_colour: "" },
    clients: [{ id: "c1", name: "The Patels" }],
    students: [
      { id: "s1", name: "Arjun Patel" },
      { id: "s2", name: "Maya Patel" },
    ],
    features: {
      cancellations: role === "client",
      absence: role === "client",
      invoices: role === "client",
      reports: true,
      profile: role === "client",
    },
    welcome_text: "Welcome to Bright Minds",
    help_url: "",
    terms_url: "",
  };
}

function routes(extra: Routes = {}, role: "client" | "student" = "client"): Routes {
  return {
    "GET /api/v1/portal/me": { body: me(role) },
    "GET /api/v1/portal/dashboard": {
      body: {
        next_lesson: LESSON,
        upcoming: [],
        reports: [],
        announcements: [
          { id: "a1", title: "Half term", body: "No lessons next week", published_at: soon },
        ],
        amount_due: gbp("40.00"),
        credit: gbp("0.00"),
      },
    },
    ...extra,
  };
}

describe("portal", () => {
  it("asks for an email and sends a sign-in link", async () => {
    window.history.pushState(null, "", "/portal/");
    const calls = mockApi({
      "GET /api/v1/portal/me": {
        status: 401,
        body: { type: "x", title: "Unauthorised", status: 401 },
      },
      "POST /api/v1/auth/magic-link": { status: 202, body: null },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Email"), {
      target: { value: "priya@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Email me a sign-in link" }));
    expect(await screen.findByText(/we sent a sign-in link/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      email: "priya@example.com",
      next: "/portal/",
    });
  });

  it("shows the next lesson and cancels it after the policy preview", async () => {
    window.history.pushState(null, "", "/portal/");
    const calls = mockApi(
      routes({
        "POST /api/v1/portal/lessons/l1/cancel": (_body, url) => ({
          body: {
            kind: "free",
            charge_percent: "0.00",
            message: "This is a free cancellation: no charge to the client.",
            makeup_credit: false,
            cancelled: !url.searchParams.get("preview"),
          },
        }),
      }),
    );
    render(<App />);
    expect(await screen.findByText("Welcome to Bright Minds")).toBeInTheDocument();
    expect(screen.getByText("You owe £40.00.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Half term" })).toBeInTheDocument();
    const card = screen.getByRole("article", { name: "Maths group" });
    fireEvent.click(within(card).getByRole("button", { name: "Cancel lesson" }));
    expect(await within(card).findByText(/free cancellation/)).toBeInTheDocument();
    fireEvent.change(within(card).getByLabelText("Reason (optional)"), {
      target: { value: "Holiday" },
    });
    fireEvent.click(within(card).getByRole("button", { name: "Confirm cancellation" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/cancel") && !c.search)?.body).toEqual({
        reason: "Holiday",
      }),
    );
  });

  it("reports one student's absence from a group lesson", async () => {
    window.history.pushState(null, "", "/portal/schedule");
    const calls = mockApi(
      routes({
        "GET /api/v1/portal/schedule": { body: [LESSON] },
        "POST /api/v1/portal/lessons/l1/absence": { status: 204, body: null },
      }),
    );
    render(<App />);
    const card = await screen.findByRole("article", { name: "Maths group" });
    fireEvent.click(within(card).getByRole("button", { name: "Can't make it" }));
    fireEvent.change(within(card).getByLabelText("Who can't come"), { target: { value: "s2" } });
    fireEvent.change(within(card).getByLabelText("Note for the tutor (optional)"), {
      target: { value: "Dentist" },
    });
    fireEvent.click(within(card).getByRole("button", { name: "Tell the tutor" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/absence"))?.body).toEqual({
        student: "s2",
        note: "Dentist",
      }),
    );
  });

  it("lists invoices with pay links and reads reports", async () => {
    window.history.pushState(null, "", "/portal/billing");
    const calls = mockApi(
      routes({
        "GET /api/v1/portal/billing": {
          body: {
            accounts: [
              {
                client: "c1",
                name: "The Patels",
                balances: {
                  currency: "GBP",
                  invoice_balance: gbp("40.00"),
                  available_credit: gbp("0.00"),
                  overdue: gbp("0.00"),
                },
                auto_pay: false,
              },
            ],
            invoices: [
              {
                id: "i1",
                number: "INV-000001",
                status: "issued",
                issue_date: "2026-10-01",
                due_date: "2026-10-15",
                total: gbp("40.00"),
                balance_due: gbp("40.00"),
                pay_token: "paytok",
                pdf_token: "paytok",
              },
            ],
            payment_requests: [],
            credit_notes: [],
          },
        },
        "GET /api/v1/portal/payment-methods": {
          body: { auto_pay: false, consent_given_at: null, methods: [] },
        },
        "GET /api/v1/portal/reports": {
          body: [
            {
              id: "r1",
              lesson_title: "Maths group",
              lesson_start: soon,
              tutor_name: "Nia Adeyemi",
              shared_at: soon,
              answers: [{ label: "What we covered", type: "rich_text", value: "Fractions" }],
              comments: [],
            },
          ],
        },
        "POST /api/v1/portal/reports/r1/comments": { status: 201, body: {} },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("link", { name: "Pay £40.00" })).toHaveAttribute(
      "href",
      "/pay/paytok",
    );
    fireEvent.click(screen.getByRole("link", { name: "Reports" }));
    expect(await screen.findByText("Fractions")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Reply to the tutor"), { target: { value: "Thanks!" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/comments"))?.body).toEqual({ body: "Thanks!" }),
    );
  });

  it("gives students a smaller menu", async () => {
    window.history.pushState(null, "", "/portal/");
    mockApi(routes({}, "student"));
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Portal menu" });
    expect(within(nav).queryByRole("link", { name: "Payments" })).not.toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Reports" })).toBeInTheDocument();
  });
});
