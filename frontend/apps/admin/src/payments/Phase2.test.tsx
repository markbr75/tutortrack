import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

const assign = vi.fn();

/** Go to ``path`` with ``location.assign`` recorded instead of navigating. */
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

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const gbp = (amount: string) => ({ amount, currency: "GBP" });

const PERMS = {
  ...ME.permissions,
  "billing.invoice.view": "all",
  "payments.payment.view": "all",
  "payments.provider.manage": "all",
  "payments.reconcile": "all",
  "people.client.view": "all",
};

function base(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/invoices": { body: { results: [], next: null } },
    "GET /api/v1/clients": { body: { results: [], next: null } },
    ...extra,
  };
}

const PAGE = {
  kind: "invoice",
  organisation: "Bright Minds",
  number: "INV-000001",
  client_name: "The Patels",
  status: "issued",
  due_date: "2026-10-23",
  total: gbp("40.00"),
  amount_due: gbp("40.00"),
  lines: [{ description: "Maths", amount: gbp("40.00") }],
  allow_partial: false,
  can_pay_online: true,
  has_pdf: false,
  providers: ["stripe", "gocardless", "paypal"],
};

describe("payments phase 2", () => {
  it("pays with PayPal on PayPal's own page", async () => {
    visit("/pay/tok_abcdefghijklmnopqrstuvwxyz");
    const calls = mockApi({
      "GET /api/v1/pay/tok_abcdefghijklmnopqrstuvwxyz": { body: PAGE },
      "POST /api/v1/pay/tok_abcdefghijklmnopqrstuvwxyz/intent": {
        body: {
          provider: "paypal",
          publishable_key: "",
          account: "M1",
          client_secret: "",
          intent: "ORDER1",
          redirect_url: "https://paypal.example/approve",
          amount: gbp("40.00"),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByLabelText("PayPal"));
    expect(screen.getByText(/PayPal's secure page/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pay £40.00" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://paypal.example/approve"));
    expect(calls.find((c) => c.path.endsWith("/intent"))?.body).toEqual({
      save_method: false,
      provider: "paypal",
    });
  });

  it("confirms a GoCardless bank payment on return", async () => {
    visit("/pay/tok_abcdefghijklmnopqrstuvwxyz?provider=gocardless&intent=BRQ1");
    const calls = mockApi({
      "GET /api/v1/pay/tok_abcdefghijklmnopqrstuvwxyz": { body: PAGE },
      "POST /api/v1/pay/tok_abcdefghijklmnopqrstuvwxyz/confirm": {
        body: { status: "processing" },
      },
    });
    render(<App />);
    expect(await screen.findByText(/being processed/)).toBeInTheDocument();
    expect(calls.find((c) => c.path.endsWith("/confirm"))?.body).toEqual({
      intent: "BRQ1",
      provider: "gocardless",
    });
  });

  it("connects GoCardless and finishes when it sends the admin back", async () => {
    visit("/settings/payments?provider=gocardless&code=abc&state=st1");
    const calls = mockApi(
      base({
        "GET /api/v1/payments/providers": { body: [] },
        "POST /api/v1/payments/providers/gocardless/complete": {
          body: { id: "pa1", provider: "gocardless", status: "active" },
        },
        "POST /api/v1/payments/providers/paypal/connect": {
          body: { account: { id: "pa2" }, url: "https://paypal.example/signup" },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Connected.")).toBeInTheDocument();
    expect(calls.find((c) => c.path.endsWith("/gocardless/complete"))?.body).toEqual({
      state: "st1",
      code: "abc",
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect PayPal" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://paypal.example/signup"));
  });

  it("confirms a suggested bank match", async () => {
    visit("/billing");
    const line = {
      id: "bt1",
      statement: "s1",
      booked_on: "2026-10-05",
      currency: "GBP",
      amount: gbp("40.00"),
      description: "FASTER PAYMENT PATEL",
      reference: "INV-000001",
      counterparty: "PATEL",
      status: "suggested",
      payment: null,
      payment_group: null,
      payout: null,
      matched_at: null,
      created_at: "2026-10-05T09:00:00Z",
      matches: [
        {
          id: "m1",
          kind: "invoice",
          invoice: "i1",
          invoice_number: "INV-000001",
          payment_request: null,
          client: "c1",
          client_name: "The Patels",
          payment: null,
          payout: null,
          score: 100,
          reason: "Invoice INV-000001 in the reference",
          status: "suggested",
        },
      ],
    };
    const calls = mockApi(
      base({
        "GET /api/v1/bank-reconciliation/transactions": { body: { results: [line], next: null } },
        "POST /api/v1/bank-reconciliation/transactions/bt1/confirm": {
          body: { ...line, status: "matched" },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Bank" }));
    expect(await screen.findByText(/Invoice INV-000001 in the reference/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/confirm"))?.body).toEqual({ match: "m1" }),
    );
  });
});
