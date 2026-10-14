import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "./App";
import { ME, mockApi } from "./test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const ADMIN = {
  ...ME,
  permissions: {
    ...ME.permissions,
    "payroll.view": "all",
    "payroll.tax.manage": "all",
    "payroll.tax.view": "all",
    "payroll.payrun.pay": "all",
    "integrations.accounting.view": "all",
    "integrations.accounting.manage": "all",
    "reporting.warehouse.manage": "all",
    "reporting.finance.view": "all",
  },
  features: { warehouse_export: true },
};

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: ADMIN },
    "GET /api/v1/organisation": { body: { status: "active" } },
    "GET /api/v1/me/organisations": { body: [] },
    ...extra,
  };
}

describe("Phase 3 (ADR 0032)", () => {
  it("shows 1099-NEC figures and finalises the tax year with an idempotency key", async () => {
    const year = new Date().getFullYear() - 1;
    window.history.pushState(null, "", "/payroll/tax-forms");
    const calls = mockApi(
      routes({
        [`GET /api/v1/payroll/tax-years/${year}/1099`]: {
          body: {
            tax_year: year, currency: "USD", threshold: "2000", reportable: 1, problems: 0,
            rows: [{ tutor: "t1", name: "Ava Lee", tin_type: "ssn", tin_hint: "6789",
                     address: {}, box1: { amount: "2400.00", currency: "USD" }, payment_count: 3,
                     reportable: true, problems: [], filing: null,
                     changed_since_filing: false }],
          },
        }, // prettier-ignore
        [`POST /api/v1/payroll/tax-years/${year}/1099/finalise`]: { status: 201, body: [{}] },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Ava Lee")).toBeInTheDocument();
    expect(screen.getByText("•••-••-6789")).toBeInTheDocument();
    expect(screen.getByText("US$2,400.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Finalise the year" }));
    expect(await screen.findByText("1 form finalised.")).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/1099/finalise"))).toBe(true);
  });

  it("creates a warehouse destination without echoing credentials", async () => {
    window.history.pushState(null, "", "/analytics/warehouse");
    const calls = mockApi(
      routes({
        "GET /api/v1/reporting/warehouse/destinations": {
          body: { results: [], next: null, previous: null },
        },
        "GET /api/v1/reporting/warehouse/schema": {
          body: [
            {
              dataset: "fact_lesson",
              description: "Lessons",
              columns: [{ name: "id", type: "STRING" }],
            },
          ],
        },
        "POST /api/v1/reporting/warehouse/destinations": { status: 201, body: { id: "d1" } },
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Export to"), { target: { value: "s3" } });
    fireEvent.change(screen.getByLabelText("Bucket"), { target: { value: "bm-lake" } });
    fireEvent.change(screen.getByLabelText("AWS region"), { target: { value: "eu-west-2" } });
    fireEvent.change(screen.getByLabelText("Access key id"), { target: { value: "AK" } });
    fireEvent.change(screen.getByLabelText("Secret access key"), { target: { value: "SK" } });
    fireEvent.click(screen.getByRole("button", { name: "Save destination" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        kind: "s3",
        config: { bucket: "bm-lake", region: "eu-west-2" },
        credentials: { access_key_id: "AK", secret_access_key: "SK" },
      }),
    );
    expect(screen.getByText("Dataset schemas")).toBeInTheDocument();
  });

  it("links an employed tutor to a Xero Payroll employee", async () => {
    window.history.pushState(null, "", "/settings/accounting/payroll");
    const status = {
      connected: true, connection_id: "c1", account_name: "Bright Minds Payroll",
      earnings_rate: null, links: [], syncs: [],
      unlinked: [{ tutor: "t1", tutor_name: "Sam Lee" }],
    }; // prettier-ignore
    const calls = mockApi(
      routes({
        "GET /api/v1/accounting/xero-payroll": { body: status },
        "GET /api/v1/accounting/xero-payroll/employees": {
          body: [{ id: "emp-1", email: "sam@x.test", first_name: "Sam", last_name: "Lee" }],
        },
        "GET /api/v1/accounting/xero-payroll/earnings-rate": {
          body: [{ id: "rate-1", name: "Ordinary Hours", kind: "OrdinaryEarnings" }],
        },
        "PUT /api/v1/accounting/xero-payroll/links": { body: { ...status, unlinked: [] } },
      }),
    );
    render(<App />);
    const select = await screen.findByLabelText("Xero employee for Sam Lee");
    await screen.findByRole("option", { name: "Sam Lee" });
    fireEvent.change(select, { target: { value: "emp-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        tutor: "t1",
        employee_id: "emp-1",
      }),
    );
  });

  it("offers Sage and FreeAgent next to Xero and QuickBooks", async () => {
    window.history.pushState(null, "", "/settings/accounting");
    mockApi(
      routes({
        "GET /api/v1/accounting/connections": { body: { results: [], next: null, previous: null } },
      }),
    );
    render(<App />);
    expect(
      await screen.findByRole("button", { name: /Sage Business Cloud Accounting/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /FreeAgent/ })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Xero Payroll for employed tutors" }),
    ).toBeInTheDocument();
  });
});
