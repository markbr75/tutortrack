import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const PERMS = {
  ...ME.permissions,
  "integrations.accounting.view": "all",
  "integrations.accounting.manage": "all",
  "integrations.accounting.export": "all",
};

const CONNECTION = {
  id: "a1",
  connection: "c1",
  provider: "xero",
  provider_name: "Xero",
  status: "active",
  account_name: "Bright Minds Ltd",
  connection_error: "",
  company_name: "Bright Minds Ltd",
  base_currency: "GBP",
  lock_date: null,
  enabled: false,
  enabled_at: null,
  mode: "individual",
  start_date: null,
  sync_bills: true,
  attach_pdf: true,
  lock_behaviour: "post_to_open",
  chart_fetched_at: "2026-10-10T10:00:00Z",
  last_sync_at: null,
  simulated: true,
  stats: { synced: 4, pending: 0, error: 1, skipped: 0 },
  problems: [] as { kind: string; key: string; message: string }[],
  backfill_progress: {},
  created_at: "2026-10-10T10:00:00Z",
};

const CHART = {
  accounts: [
    { id: "acc-200", code: "200", name: "Tuition Sales", type: "revenue", active: true },
    { id: "acc-210", code: "210", name: "Other Revenue", type: "revenue", active: true },
  ],
  tax_codes: [{ id: "OUTPUT2", name: "20% (VAT on Income)", rate: "20", active: true }],
  tracking: [],
};

const MAPPINGS = {
  provider: "xero",
  accounts: [{ kind: "revenue", key: "default", external_id: "acc-200", code: "200", name: "" }],
  taxes: [],
  tracking: [],
  kinds: [{ kind: "revenue", name: "Sales (revenue)", is_required: true }],
  revenue_keys: [],
  clearing_keys: [],
  expense_keys: [],
  tax_rates: [{ key: "t1", name: "VAT (20%)" }],
  branches: [],
  problems: [{ kind: "tax", key: "", message: "Choose a tax code for “No tax”." }],
};

const ERROR_RECORD = {
  id: "r1",
  connection: "a1",
  provider: "xero",
  object_type: "invoice",
  object_id: "i1",
  label: "INV-000042",
  external_id: "",
  external_number: "",
  status: "error",
  error: "Account code 200 is archived in Xero.",
  error_code: "account_archived",
  attempts: 1,
  last_attempt_at: null,
  synced_at: null,
  posted_date: null,
  updated_at: "2026-10-10T10:00:00Z",
};

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
    "GET /api/v1/organisation": { body: { status: "active" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/accounting/connections": { body: { results: [CONNECTION] } },
    "GET /api/v1/accounting/connections/a1/chart": { body: CHART },
    "GET /api/v1/accounting/mappings/xero": { body: MAPPINGS },
    "GET /api/v1/accounting/mappings/export": { body: { ...MAPPINGS, provider: "export" } },
    "GET /api/v1/accounting/records": (_body, url) => ({
      body: { results: url.searchParams.get("status") === "error" ? [ERROR_RECORD] : [] },
    }),
    ...extra,
  };
}

describe("accounting settings", () => {
  it("connects Xero when nothing is connected", async () => {
    window.history.pushState(null, "", "/settings/accounting");
    const assign = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      assign,
      search: "",
      pathname: "/settings/accounting",
    });
    const calls = mockApi(
      routes({
        "GET /api/v1/accounting/connections": { body: { results: [] } },
        "POST /api/v1/integrations/oauth/start": {
          body: { authorize_url: "https://login.xero.example/authorize" },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect Xero" }));
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://login.xero.example/authorize"),
    );
    expect(calls.find((c) => c.path.endsWith("/oauth/start"))?.body).toEqual({
      provider: "xero",
      level: "organisation",
      next: "/settings/accounting",
    });
  });

  it("maps accounts, shows what is missing and switches sync on", async () => {
    window.history.pushState(null, "", "/settings/accounting");
    const calls = mockApi(
      routes({
        "PUT /api/v1/accounting/mappings/xero": { body: { ...MAPPINGS, problems: [] } },
        "POST /api/v1/accounting/connections/a1/enable": {
          body: { ...CONNECTION, enabled: true, start_date: "2026-10-10" },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Accounting" })).toBeInTheDocument();
    const form = await screen.findByRole("form", { name: "Xero mappings" });
    expect(within(form).getByText("Choose a tax code for “No tax”.")).toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText("Sales (revenue) *"), {
      target: { value: "acc-210" },
    });
    fireEvent.change(within(form).getByLabelText("No tax"), { target: { value: "OUTPUT2" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save mappings" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        accounts: [{ kind: "revenue", key: "default", external_id: "acc-210" }],
        taxes: [{ tax_rate: null, external_id: "OUTPUT2" }],
        tracking: [],
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Switch sync on" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/accounting/connections/a1/enable")).toBe(true),
    );
  });

  it("lists sync errors with retry and skip", async () => {
    window.history.pushState(null, "", "/settings/accounting");
    const calls = mockApi(
      routes({
        "POST /api/v1/accounting/records/r1/retry": {
          body: { ...ERROR_RECORD, status: "pending" },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Account code 200 is archived in Xero.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/accounting/records/r1/retry")).toBe(true),
    );
    expect(screen.getByRole("button", { name: "Skip" })).toBeInTheDocument();
  });
});
