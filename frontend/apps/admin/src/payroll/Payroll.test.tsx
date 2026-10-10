import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const gbp = (amount: string) => ({ amount, currency: "GBP" });

const FINANCE = {
  ...ME,
  membership: { ...ME.membership, role: "finance" },
  permissions: {
    ...ME.permissions,
    "payroll.view": "all",
    "payroll.payrun.create": "all",
    "payroll.payrun.approve": "all",
    "payroll.payrun.pay": "all",
    "payroll.expense.approve": "all",
    "payroll.item.manage": "all",
  },
};

const RUN = {
  id: "r1", number: "PR-000001", all_branches: true, branch: "b1", period_start: "2026-09-01",
  period_end: "2026-09-30", status: "review", totals: { GBP: "412.50" },
  warnings: [{ code: "no_bank_details", message: "Sam Lee has no bank details." }],
  approvals: [], approvals_required: 1, approved_at: null, paid_at: null,
  created_at: "2026-10-01T07:00:00Z",
  payouts: [
    { id: "p1", tutor: "t1", tutor_name: "Nia Okafor", amount: gbp("412.50"),
      method: "bank_file", status: "pending", provider_ref: "", reference: "",
      failure_reason: "", paid_at: null, statement: null },
  ],
  bank_files: [],
}; // prettier-ignore

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: FINANCE },
    "GET /api/v1/organisation": { body: { status: "active" } },
    "GET /api/v1/me/organisations": { body: [] },
    ...extra,
  };
}

describe("payroll", () => {
  it("reviews and approves a pay run, then makes the bank file", async () => {
    window.history.pushState(null, "", "/payroll/runs/r1");
    const calls = mockApi(
      routes({
        "GET /api/v1/pay-runs/r1": { body: RUN },
        "POST /api/v1/pay-runs/r1/approve": { body: { ...RUN, status: "approved" } },
        "POST /api/v1/pay-runs/r1/bank-files": {
          status: 201,
          body: { id: "f1", format: "bacs18", filename: "PR-000001-bacs18.txt", payout_count: 1,
                  total: { GBP: "412.50" }, created_at: "2026-10-01T08:00:00Z" },
        }, // prettier-ignore
      }),
    );
    render(<App />);
    expect(await screen.findByText("Sam Lee has no bank details.")).toBeInTheDocument();
    expect(screen.getAllByText("£412.50").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.change(await screen.findByLabelText("Bank file"), { target: { value: "bacs18" } });
    fireEvent.click(screen.getByRole("button", { name: "Make bank file" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/bank-files"))?.body).toEqual({
        format: "bacs18",
      }),
    );
  });

  it("approves an expense claim", async () => {
    window.history.pushState(null, "", "/payroll/expenses");
    const claim = {
      id: "e1", tutor: "t1", tutor_name: "Nia Okafor", category: "c1", category_name: "Books",
      status: "submitted", date: "2026-10-08", description: "Workbook", amount: gbp("12.00"),
      tax: gbp("0.00"), distance: null, receipt: null, lesson: null, job: null, client: "cl1",
      rebillable: true, submitted_at: "2026-10-08T10:00:00Z", decided_by_name: "",
      decided_at: null, decision_comment: "", charge_id: null,
    }; // prettier-ignore
    const calls = mockApi(
      routes({
        "GET /api/v1/expenses": { body: { results: [claim], next: null, previous: null } },
        "POST /api/v1/expenses/e1/approve": { body: { ...claim, status: "approved" } },
      }),
    );
    render(<App />);
    expect(await screen.findByText(/Rebill to client/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await vi.waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/expenses/e1/approve")).toBe(true),
    );
  });
});
