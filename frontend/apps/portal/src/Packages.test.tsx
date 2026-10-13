import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "./App";
import { mockApi } from "./test-utils";

const assign = vi.fn();

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const gbp = (amount: string) => ({ amount, currency: "GBP" });

function visit(path: string) {
  assign.mockReset();
  window.history.pushState(null, "", path);
  const loc = window.location;
  vi.stubGlobal("location", {
    assign,
    replace: vi.fn(),
    reload: vi.fn(),
    pathname: loc.pathname,
    search: loc.search,
    hash: loc.hash,
    href: loc.href,
    origin: loc.origin,
    host: loc.host,
    hostname: loc.hostname,
    protocol: loc.protocol,
    port: loc.port,
  });
}

describe("portal packages (E10-T12, FR-15-7)", () => {
  it("shows what is left and buys a package", async () => {
    visit("/portal/billing");
    const calls = mockApi({
      "GET /api/v1/portal/me": {
        body: {
          role: "client",
          organisation: { name: "Bright Minds", primary_colour: "" },
          clients: [{ id: "c1", name: "The Patels" }],
          students: [],
          features: {
            cancellations: true,
            absence: true,
            invoices: true,
            reports: true,
            profile: true,
          },
          welcome_text: "",
          help_url: "",
          terms_url: "",
        },
      },
      "GET /api/v1/portal/billing": {
        body: {
          accounts: [
            {
              client: "c1",
              name: "The Patels",
              balances: {
                currency: "GBP",
                invoice_balance: gbp("0.00"),
                available_credit: gbp("0.00"),
                overdue: gbp("0.00"),
              },
              auto_pay: false,
            },
          ],
          invoices: [],
          payment_requests: [],
          credit_notes: [],
          packages: [
            {
              id: "p1",
              client: "c1",
              name: "10 hours",
              status: "active",
              quantity_type: "hours",
              units_total: "10.00",
              units_remaining: "7.50",
              student_name: "Arjun Patel",
              expires_at: null,
            },
          ],
          package_offers: [
            {
              id: "t1",
              name: "5 lessons",
              description: "",
              quantity_type: "lessons",
              quantity: "5.00",
              price: gbp("150.00"),
              validity_days: 90,
            },
          ],
        },
      },
      "GET /api/v1/portal/payment-methods": {
        body: { auto_pay: false, consent_given_at: null, methods: [] },
      },
      "POST /api/v1/portal/packages": { status: 201, body: { package: "p2", pay_token: "tok" } },
    });
    render(<App />);
    expect(await screen.findByText(/7.5 of 10 hours left/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Buy" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/pay/tok"));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ client: "c1", template: "t1" });
  });
});
