import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

type Routes = Parameters<typeof mockApi>[0];

const PERMS = {
  ...ME.permissions,
  "billing.invoice.view": "all",
  "billing.invoice.create": "all",
  "billing.invoice.issue": "all",
  "billing.invoice.void": "all",
  "billing.invoice.write_off": "all",
  "billing.credit_note.issue": "all",
  "billing.charge.view": "all",
  "billing.charge.create": "all",
  "billing.payment_request.view": "all",
  "billing.payment_request.manage": "all",
  "billing.ledger.view": "all",
  "people.client.view": "all",
};

const gbp = (amount: string) => ({ amount, currency: "GBP" });

function invoice(extra: Record<string, unknown> = {}) {
  return {
    id: "i1",
    number: "",
    client: "c1",
    client_name: "The Patels",
    branch: "b1",
    currency: "GBP",
    status: "draft",
    is_overdue: false,
    issue_date: null,
    due_date: null,
    period_start: "2026-09-01",
    period_end: "2026-09-30",
    subtotal: gbp("80.00"),
    tax_total: gbp("0.00"),
    total: gbp("80.00"),
    amount_paid: gbp("0.00"),
    amount_credited: gbp("0.00"),
    balance_due: gbp("80.00"),
    po_number: "",
    notes: "",
    sent_at: null,
    invoice_run: null,
    created_at: "2026-10-01T09:00:00Z",
    billing_snapshot: {},
    lines: [
      {
        id: "l1",
        charge: "ch1",
        position: 0,
        date: "2026-09-08",
        description: "Maths 1:1 – Arjun Patel",
        student_name: "Arjun Patel",
        tutor_name: "Nia Adeyemi",
        quantity: "1.0000",
        unit: "lesson",
        unit_price: gbp("40.0000"),
        tax_percent: "0.000",
        net: gbp("40.00"),
        tax: gbp("0.00"),
        gross: gbp("40.00"),
        credited: gbp("0.00"),
      },
      {
        id: "l2",
        charge: "ch2",
        position: 1,
        date: "2026-09-15",
        description: "Maths 1:1 – Maya Patel",
        student_name: "Maya Patel",
        tutor_name: "Nia Adeyemi",
        quantity: "1.0000",
        unit: "lesson",
        unit_price: gbp("40.0000"),
        tax_percent: "0.000",
        net: gbp("40.00"),
        tax: gbp("0.00"),
        gross: gbp("40.00"),
        credited: gbp("0.00"),
      },
    ],
    credit_notes: [],
    ...extra,
  };
}

function base(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    ...extra,
  };
}

describe("billing", () => {
  it("issues a draft and credits part of a line", async () => {
    window.history.pushState(null, "", "/invoices/i1");
    const issued = invoice({
      number: "INV-000001",
      status: "issued",
      issue_date: "2026-10-01",
      due_date: "2026-10-15",
    });
    let current: object = invoice();
    const calls = mockApi(
      base({
        "GET /api/v1/invoices/i1": () => ({ body: current }),
        "POST /api/v1/invoices/i1/issue": () => {
          current = issued;
          return { body: issued };
        },
        "POST /api/v1/invoices/i1/credit-note": {
          status: 201,
          body: { id: "cn1", number: "CN-000001" },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: /Draft invoice/ })).toBeInTheDocument();
    expect(screen.getAllByText("£80.00", { selector: "dd" })).toHaveLength(2); // total, due
    fireEvent.click(screen.getByRole("button", { name: "Issue invoice" }));
    expect(await screen.findByRole("heading", { name: /INV-000001/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Credit note" }));
    fireEvent.change(screen.getByLabelText("Credit for Maths 1:1 – Arjun Patel"), {
      target: { value: "15" },
    });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Cut short" } });
    fireEvent.click(screen.getByRole("button", { name: "Issue credit note" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/credit-note"))?.body).toEqual({
        reason: "Cut short",
        application: "invoice",
        lines: [{ line: "l1", amount: "15" }],
      }),
    );
  });

  it("voids an issued invoice with a reason", async () => {
    window.history.pushState(null, "", "/invoices/i1");
    const issued = invoice({ number: "INV-000002", status: "issued", due_date: "2026-10-15" });
    const calls = mockApi(
      base({
        "GET /api/v1/invoices/i1": { body: issued },
        "POST /api/v1/invoices/i1/void": { body: { ...issued, status: "void" } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Void" }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Wrong family" } });
    fireEvent.click(screen.getByRole("button", { name: "Void invoice" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/void"))?.body).toEqual({
        reason: "Wrong family",
      }),
    );
    expect(await screen.findByText("Void")).toBeInTheDocument();
  });

  it("previews and starts an invoice run", async () => {
    window.history.pushState(null, "", "/billing");
    const calls = mockApi(
      base({
        "GET /api/v1/invoices": { body: { results: [], next: null } },
        "GET /api/v1/invoice-runs": { body: { results: [], next: null } },
        "POST /api/v1/invoice-runs/preview": {
          body: { clients: 3, charges: 7, totals: { GBP: "280.00" } },
        },
        "POST /api/v1/invoice-runs": {
          status: 201,
          body: {
            id: "r1",
            branch: "b1",
            period_start: "2026-09-01",
            period_end: "2026-09-30",
            mode: "arrears",
            filters: {},
            status: "collecting",
            stats: {},
            review_until: null,
            approved_at: null,
            created_at: "2026-10-01T09:00:00Z",
          },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Invoice runs" }));
    const form = await screen.findByRole("form", { name: "Run invoicing" });
    fireEvent.change(within(form).getByLabelText("From"), { target: { value: "2026-09-01" } });
    fireEvent.change(within(form).getByLabelText("To"), { target: { value: "2026-09-30" } });
    fireEvent.click(within(form).getByRole("button", { name: "Preview" }));
    expect(
      await screen.findByText("7 charges for 3 clients would be invoiced."),
    ).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Run invoicing" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === "/api/v1/invoice-runs" && c.method === "POST")?.body,
      ).toEqual({ period_start: "2026-09-01", period_end: "2026-09-30", mode: "arrears" }),
    );
  });

  it("shows a client's balances and adds a charge", async () => {
    window.history.pushState(null, "", "/clients/c1");
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
        "GET /api/v1/activity": { body: { results: [], next: null } },
        "GET /api/v1/clients/c1/balance": {
          body: {
            currency: "GBP",
            ledger: gbp("55.00"),
            invoice_balance: gbp("95.00"),
            available_credit: gbp("40.00"),
            uninvoiced: gbp("20.00"),
            projected: gbp("20.00"),
            overdue: gbp("0.00"),
          },
        },
        "GET /api/v1/invoices": { body: { results: [], next: null } },
        "POST /api/v1/charges": { status: 201, body: { id: "ch9" } },
      }),
    );
    render(<App />);
    expect(await screen.findByText("£95.00")).toBeInTheDocument();
    expect(screen.getByText("£40.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Add a charge" }));
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Workbook" } });
    fireEvent.change(screen.getByLabelText(/^Amount/), { target: { value: "-5" } });
    fireEvent.click(screen.getByRole("button", { name: "Add a charge" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/charges")?.body).toEqual({
        client: "c1",
        description: "Workbook",
        unit_price: { amount: "-5", currency: "GBP" },
        quantity: "1",
        category: "",
      }),
    );
  });
});
