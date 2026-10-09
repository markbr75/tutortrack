import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  delete window.Stripe;
  window.history.pushState(null, "", "/");
});

const gbp = (amount: string) => ({ amount, currency: "GBP" });

const PERMS = {
  ...ME.permissions,
  "billing.invoice.view": "all",
  "payments.payment.view": "all",
  "payments.payment.record": "all",
  "payments.payment.refund": "all",
  "payments.provider.manage": "all",
  "payments.autopay.manage": "all",
  "people.client.view": "all",
};

function base(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    ...extra,
  };
}

/** A stand-in for Stripe.js: Elements mount nothing and confirmations succeed. */
function fakeStripe() {
  const confirmPayment = vi.fn(async () => ({
    paymentIntent: { id: "pi_1", status: "succeeded" },
  }));
  const confirmSetup = vi.fn(async () => ({ setupIntent: { id: "seti_1", status: "succeeded" } }));
  window.Stripe = vi.fn(() => ({
    elements: () => ({ create: () => ({ mount: vi.fn(), destroy: vi.fn() }) }),
    confirmPayment,
    confirmSetup,
  })) as unknown as typeof window.Stripe;
  return { confirmPayment, confirmSetup };
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
  lines: [{ description: "Maths 1:1 – Arjun Patel", amount: gbp("40.00") }],
  allow_partial: false,
  can_pay_online: true,
  has_pdf: true,
};

describe("payments", () => {
  it("pays an invoice on the hosted page", async () => {
    window.history.pushState(null, "", "/pay/tok_abcdefghijklmnopqrstuvwxyz");
    const stripe = fakeStripe();
    const calls = mockApi({
      "GET /api/v1/pay/tok_abcdefghijklmnopqrstuvwxyz": { body: PAGE },
      "POST /api/v1/pay/tok_abcdefghijklmnopqrstuvwxyz/intent": {
        body: {
          publishable_key: "pk_test",
          account: "acct_1",
          client_secret: "pi_1_secret",
          intent: "pi_1",
          amount: gbp("40.00"),
        },
      },
      "POST /api/v1/pay/tok_abcdefghijklmnopqrstuvwxyz/confirm": {
        body: { status: "succeeded" },
      },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Invoice INV-000001" })).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Save these details for future payments"));
    fireEvent.click(screen.getByRole("button", { name: "Pay £40.00" }));
    const payNow = await screen.findByRole("button", { name: "Pay now" });
    await waitFor(() => expect(payNow).toBeEnabled());
    fireEvent.click(payNow);
    expect(await screen.findByText(/your payment has been received/)).toBeInTheDocument();
    expect(stripe.confirmPayment).toHaveBeenCalledTimes(1);
    expect(window.Stripe).toHaveBeenCalledWith("pk_test", { stripeAccount: "acct_1" });
    expect(calls.find((c) => c.path.endsWith("/intent"))?.body).toEqual({ save_method: true });
    expect(calls.find((c) => c.path.endsWith("/confirm"))?.body).toEqual({ intent: "pi_1" });
  });

  it("saves a card and agrees to auto-pay from a setup link", async () => {
    window.history.pushState(null, "", "/pay/setup/setup_token_abcdefghijklmnop");
    fakeStripe();
    const calls = mockApi({
      "GET /api/v1/pay/setup/setup_token_abcdefghijklmnop": {
        body: {
          organisation: "Bright Minds",
          client_name: "The Patels",
          publishable_key: "pk_test",
          account: "acct_1",
          client_secret: "seti_1_secret",
          intent: "seti_1",
          consent_text: "I authorise Bright Minds to charge my saved payment method.",
        },
      },
      "POST /api/v1/pay/setup/setup_token_abcdefghijklmnop": {
        body: {
          method: { id: "pm1", type: "card", brand: "visa", last4: "4242", is_default: true },
          auto_pay: true,
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByLabelText(/I authorise Bright Minds/));
    const save = screen.getByRole("button", { name: "Save details" });
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.click(save);
    expect(await screen.findByText(/ending 4242/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      intent: "seti_1",
      autopay: true,
    });
  });

  it("records a bank transfer against a chosen invoice", async () => {
    window.history.pushState(null, "", "/clients/c1");
    const invoice = {
      id: "i1",
      number: "INV-000001",
      client: "c1",
      client_name: "The Patels",
      currency: "GBP",
      status: "issued",
      is_overdue: false,
      due_date: "2026-10-23",
      total: gbp("40.00"),
      balance_due: gbp("40.00"),
    };
    const calls = mockApi(
      base({
        "GET /api/v1/clients/c1": {
          body: {
            id: "c1",
            display_name: "The Patels",
            status: "active",
            currency: "GBP",
            contacts: [],
            students: [],
          },
        },
        "GET /api/v1/notes": { body: { results: [], next: null } },
        "GET /api/v1/clients/c1/balance": {
          body: {
            currency: "GBP",
            ledger: gbp("40.00"),
            invoice_balance: gbp("40.00"),
            available_credit: gbp("0.00"),
            uninvoiced: gbp("0.00"),
            projected: gbp("0.00"),
            overdue: gbp("0.00"),
          },
        },
        "GET /api/v1/invoices": { body: { results: [invoice], next: null } },
        "GET /api/v1/payments": { body: { results: [], next: null } },
        "POST /api/v1/payments": { status: 201, body: { id: "p1" } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Payments" }));
    const form = await screen.findByRole("form", { name: "Record payment" });
    fireEvent.change(within(form).getByLabelText("Amount"), { target: { value: "40" } });
    fireEvent.change(within(form).getByLabelText("Reference"), { target: { value: "PATEL" } });
    fireEvent.click(within(form).getByLabelText("Choose which invoices it pays"));
    fireEvent.change(within(form).getByLabelText(/Pay INV-000001/), { target: { value: "40" } });
    fireEvent.click(within(form).getByRole("button", { name: "Record payment" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === "/api/v1/payments" && c.method === "POST")?.body,
      ).toMatchObject({
        client: "c1",
        amount: { amount: "40", currency: "GBP" },
        method: "bank_transfer",
        reference: "PATEL",
        allocations: [{ invoice: "i1", amount: "40" }],
      }),
    );
  });

  it("connects Stripe from settings", async () => {
    window.history.pushState(null, "", "/settings/payments");
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    mockApi(
      base({
        "GET /api/v1/payments/providers": { body: [] },
        "POST /api/v1/payments/providers/stripe/connect": {
          body: { account: { id: "a1" }, url: "https://connect.stripe.com/setup/xyz" },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect Stripe" }));
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://connect.stripe.com/setup/xyz"),
    );
  });

  it("refunds a payment from the billing area", async () => {
    window.history.pushState(null, "", "/billing");
    const calls = mockApi(
      base({
        "GET /api/v1/invoices": { body: { results: [], next: null } },
        "GET /api/v1/payments": {
          body: {
            results: [
              {
                id: "p1",
                client: "c1",
                client_name: "The Patels",
                currency: "GBP",
                amount: gbp("40.00"),
                method: "card",
                status: "succeeded",
                received_at: "2026-10-01T10:00:00Z",
                reference: "pi_1",
              },
            ],
            next: null,
          },
        },
        "POST /api/v1/payments/p1/refund": { status: 201, body: { id: "r1" } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Payments" }));
    fireEvent.click(await screen.findByRole("button", { name: "Refund" }));
    const form = screen.getByRole("form", { name: "Refund" });
    fireEvent.change(within(form).getByLabelText(/Refund amount/), { target: { value: "15" } });
    fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Cut short" } });
    fireEvent.click(within(form).getByRole("button", { name: "Refund" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/refund"))?.body).toEqual({
        amount: "15",
        reason: "Cut short",
        credit_note: false,
      }),
    );
  });
});
