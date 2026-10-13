import { fireEvent, render, screen, waitFor } from "@testing-library/react";

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
  "billing.package.view": "all",
  "billing.package.sell": "all",
  "billing.package.manage": "all",
  "billing.plan.view": "all",
  "billing.plan.manage": "all",
  "billing.late_fee.manage": "all",
  "billing.collections.manage": "all",
  "billing.split.manage": "all",
  "people.client.view": "all",
};

const gbp = (amount: string) => ({ amount, currency: "GBP" });
const page = <T,>(results: T[]) => ({ body: { results, next: null, previous: null } });

function base(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/invoices": page([]),
    "GET /api/v1/clients": page([{ id: "c1", display_name: "The Patels" }]),
    ...extra,
  };
}

const PACKAGE = {
  id: "p1",
  client: "c1",
  client_name: "The Patels",
  student: null,
  student_name: "",
  template: "t1",
  name: "10 hours",
  quantity_type: "hours",
  units_total: "10.0000",
  units_used: "2.5000",
  units_expired: "0.0000",
  units_remaining: "7.5000",
  currency: "GBP",
  price: gbp("350.00"),
  shareable: false,
  auto_renew: false,
  status: "active",
  source: "sale",
  invoice: "i1",
  invoice_number: "INV-000001",
  activated_at: "2026-10-01T09:00:00Z",
  expires_at: "2026-12-30T09:00:00Z",
  closed_at: null,
  close_reason: "",
  created_at: "2026-10-01T09:00:00Z",
};

async function openTab(name: string) {
  window.history.pushState(null, "", "/billing");
  render(<App />);
  fireEvent.click(await screen.findByRole("tab", { name }));
}

describe("billing phase 2", () => {
  it("lists packages and sells one", async () => {
    const calls = mockApi(
      base({
        "GET /api/v1/packages": page([PACKAGE]),
        "GET /api/v1/catalogue/packages": page([
          { id: "t1", name: "10 hours", price: gbp("350.00") },
        ]),
        "POST /api/v1/packages": { status: 201, body: { ...PACKAGE, status: "pending" } },
      }),
    );
    await openTab("Packages");
    expect(await screen.findByText("7.5 of 10 hours left", { exact: false })).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("Client"), { target: { value: "c1" } });
    await screen.findByRole("option", { name: "10 hours · £350.00" });
    fireEvent.change(screen.getByLabelText("Package"), { target: { value: "t1" } });
    fireEvent.click(screen.getByRole("button", { name: "Sell package" }));
    expect(await screen.findByText(/Invoice INV-000001/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ client: "c1", template: "t1" });
  });

  it("creates and pauses a recurring fee", async () => {
    const plan = {
      id: "bp1",
      client: "c1",
      client_name: "The Patels",
      job: null,
      student: null,
      description: "Monthly tuition",
      currency: "GBP",
      amount: gbp("160.00"),
      tax_rate: null,
      interval: "monthly",
      anchor_date: "2026-10-01",
      start_date: "2026-10-01",
      end_date: null,
      prorate: true,
      attendance_independent: true,
      status: "active",
      paused_at: null,
      created_at: "2026-10-01T09:00:00Z",
    };
    const calls = mockApi(
      base({
        "GET /api/v1/billing-plans": page([plan]),
        "POST /api/v1/billing-plans": { status: 201, body: plan },
        "POST /api/v1/billing-plans/bp1/status": { body: { ...plan, status: "paused" } },
      }),
    );
    await openTab("Recurring fees");
    expect(await screen.findByText(/Monthly tuition/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/billing-plans/bp1/status")?.body).toEqual({
        status: "paused",
      }),
    );
    fireEvent.change(await screen.findByLabelText("Client"), { target: { value: "c1" } });
    await screen.findByRole("option", { name: "The Patels" });
    fireEvent.change(screen.getByLabelText("Client"), { target: { value: "c1" } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Weekly class" } });
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("Starts"), { target: { value: "2026-10-07" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.method === "POST" && c.path === "/api/v1/billing-plans")?.body,
      ).toEqual({
        client: "c1",
        description: "Weekly class",
        amount: gbp("30"),
        interval: "monthly",
        start_date: "2026-10-07",
        prorate: true,
        attendance_independent: true,
      }),
    );
  });

  it("saves the late fee rule and closes a collections case", async () => {
    const calls = mockApi(
      base({
        "GET /api/v1/billing/late-fee-rules": { body: [] },
        "POST /api/v1/billing/late-fee-rules": { status: 201, body: { id: "r1" } },
        "GET /api/v1/billing/collections": page([
          {
            id: "cc1",
            client: "c1",
            client_name: "The Patels",
            invoice: "i1",
            invoice_number: "INV-000009",
            balance_due: gbp("80.00"),
            status: "open",
            block: "soft",
            task_id: "",
            opened_at: "2026-10-01T09:00:00Z",
            closed_at: null,
            close_reason: "",
          },
        ]),
        "POST /api/v1/billing/collections/cc1/close": { body: { id: "cc1", status: "closed" } },
      }),
    );
    await openTab("Late fees");
    expect(await screen.findByText(/INV-000009/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "12.50" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(
      calls.find((c) => c.path === "/api/v1/billing/late-fee-rules" && c.method === "POST")?.body,
    ).toMatchObject({ kind: "fixed", amount: "12.50", days_overdue: 14 });
    fireEvent.click(screen.getByRole("button", { name: "Take out of collections" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/close"))).toBe(true));
  });

  it("splits a job's billing 50/50", async () => {
    const calls = mockApi(
      base({
        "GET /api/v1/clients": page([
          { id: "c1", display_name: "Mum" },
          { id: "c2", display_name: "Dad" },
        ]),
        "GET /api/v1/jobs": page([{ id: "j1", reference: "J-1", name: "Maths" }]),
        "GET /api/v1/billing/splits": { body: { job: "j1", student: null, shares: [] } },
        "POST /api/v1/billing/splits": { body: { job: "j1", student: null, shares: [] } },
      }),
    );
    await openTab("Split billing");
    await screen.findByRole("option", { name: "J-1 Maths" });
    fireEvent.change(screen.getByLabelText("Job"), { target: { value: "j1" } });
    expect(await screen.findByText(/Not split/)).toBeInTheDocument();
    await screen.findAllByRole("option", { name: "Dad" });
    fireEvent.change(screen.getByLabelText("Client 1"), { target: { value: "c1" } });
    fireEvent.change(screen.getByLabelText("Client 2"), { target: { value: "c2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save split" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        job: "j1",
        shares: [
          { client: "c1", percent: "50" },
          { client: "c2", percent: "50" },
        ],
      }),
    );
  });
});
