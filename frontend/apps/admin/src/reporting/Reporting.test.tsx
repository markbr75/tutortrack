import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const OWNER = {
  ...ME,
  permissions: {
    ...ME.permissions,
    "reporting.dashboard.view": "all",
    "reporting.finance.view": "all",
    "reporting.export": "all",
    "reporting.schedule.manage": "all",
  },
};

const BASE = {
  "GET /api/v1/me": { body: OWNER },
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};

const widget = (key: string, title: string, extra = {}) => ({
  widget: { key, title, category: "finance", kind: "kpi", default_size: "s", report: "revenue" },
  unit: "money",
  period: { from: "2026-10-01", to: "2026-10-31" },
  previous_period: { from: "2026-09-01", to: "2026-09-30" },
  values: [],
  series: [],
  rows: [],
  report_params: { period: "this_month" },
  ...extra,
});

const REVENUE_DEF = {
  key: "revenue",
  title: "Revenue",
  category: "finance",
  category_label: "Finance",
  description: "Charges earned in the period.",
  filters: ["branch"],
  group_by: [
    { value: "month", label: "Month" },
    { value: "tutor", label: "Tutor" },
  ],
  period: true,
  default_period: "this_month",
};

describe("reporting", () => {
  it("shows the dashboard with KPI tiles and comparisons, and saves a customised layout", async () => {
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/reporting/dashboard": {
        body: {
          preset: "simple",
          customised: false,
          widgets: [
            { widget: "revenue", size: "s" },
            { widget: "lessons", size: "s" },
          ],
        },
      },
      "GET /api/v1/reporting/widgets/revenue": {
        body: widget("revenue", "Revenue", {
          values: [{ label: "", currency: "GBP", value: "1200.00", previous: "1000.00" }],
        }),
      },
      "GET /api/v1/reporting/widgets/lessons": {
        body: widget("lessons", "Lessons delivered", {
          unit: "count",
          values: [{ label: "Lessons", currency: "", value: "12", previous: "12" }],
        }),
      },
      "GET /api/v1/reporting/widgets": {
        body: [
          { key: "revenue", title: "Revenue", category: "finance", kind: "kpi", default_size: "s", report: "revenue" },
          { key: "lessons", title: "Lessons delivered", category: "operations", kind: "kpi", default_size: "s", report: "lessons" },
        ],
      }, // prettier-ignore
      "PUT /api/v1/reporting/dashboard": (body) => ({
        body: { preset: "custom", customised: true, ...(body as object) },
      }),
    });
    render(<App />);
    const revenue = await screen.findByRole("region", { name: "Revenue" });
    expect(await within(revenue).findByText("£1,200.00")).toBeInTheDocument();
    expect(within(revenue).getByText("Up 20% on the previous period")).toBeInTheDocument();
    expect(within(revenue).getByRole("link", { name: "Open the Revenue report" })).toHaveAttribute(
      "href",
      "/analytics/revenue?period=this_month",
    );
    const lessons = screen.getByRole("region", { name: "Lessons delivered" });
    expect(await within(lessons).findByText("Same as the previous period")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Customise" }));
    fireEvent.click(await screen.findByRole("button", { name: "Move Lessons delivered earlier" }));
    fireEvent.change(screen.getByLabelText("Size of Revenue"), { target: { value: "l" } });
    fireEvent.click(screen.getByRole("button", { name: "Save layout" }));
    await screen.findByRole("button", { name: "Customise" });
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      widgets: [
        { widget: "lessons", size: "s" },
        { widget: "revenue", size: "l" },
      ],
    });
  });

  it("runs a report with grouping, shows a table with totals and offers downloads", async () => {
    window.history.pushState(null, "", "/analytics/revenue?period=this_month");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/reporting/reports": { body: [REVENUE_DEF] },
      "GET /api/v1/reporting/reports/revenue": (_body, url) => ({
        body: {
          report: REVENUE_DEF,
          params: Object.fromEntries(url.searchParams.entries()),
          period: { from: "2026-10-01", to: "2026-10-31" },
          columns: [
            { key: "group", label: url.searchParams.get("group_by") === "tutor" ? "Tutor" : "Month", type: "text" },
            { key: "currency", label: "Currency", type: "text" },
            { key: "net", label: "Net", type: "money" },
          ],
          rows: [
            { group: "Nia Okafor", currency: "GBP", net: "40.00" },
            { group: "Sam Lee", currency: "GBP", net: "60.00" },
          ],
          totals: [{ currency: "GBP", net: "100.00" }],
          chart: { kind: "bar", x: "group", y: ["net"], stacked: false },
          notes: [],
          generated_at: "2026-10-10T09:00:00Z",
        },
      }), // prettier-ignore
      "POST /api/v1/saved-reports": { status: 201, body: { id: "s1" } },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Revenue" })).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Revenue" });
    expect(within(table).getByText("£40.00")).toBeInTheDocument();
    expect(within(table).getByText("£100.00")).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: "Chart of Revenue" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "tutor" } });
    expect(await screen.findByRole("columnheader", { name: "Tutor" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Excel" }).getAttribute("href")).toContain(
      "file_format=xlsx",
    );
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "By tutor" } });
    fireEvent.click(screen.getByRole("button", { name: "Save this view" }));
    expect(await screen.findByRole("status")).toHaveTextContent("View saved.");
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      name: "By tutor",
      report_key: "revenue",
      params: { period: "this_month", group_by: "tutor" },
    });
  });

  it("lists saved views and schedules one to be emailed", async () => {
    window.history.pushState(null, "", "/analytics/saved");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/saved-reports": {
        body: {
          results: [
            { id: "s1", name: "Monthly revenue", report_key: "revenue", params: { period: "last_month" },
              shared: false, owner_name: "Sam", is_mine: true, created_at: "", updated_at: "" },
          ],
          next: null, previous: null,
        },
      }, // prettier-ignore
      "GET /api/v1/scheduled-reports": { body: { results: [], next: null, previous: null } },
      "GET /api/v1/report-runs": { body: { results: [], next: null, previous: null } },
      "GET /api/v1/scheduled-reports/recipients": {
        body: [{ id: "u2", name: "Fin Ance", email: "fin@example.com" }],
      },
      "POST /api/v1/scheduled-reports": { status: 201, body: { id: "x1" } },
    });
    render(<App />);
    expect(await screen.findByRole("link", { name: "Monthly revenue" })).toHaveAttribute(
      "href",
      "/analytics/revenue?period=last_month",
    );
    fireEvent.click(screen.getByRole("button", { name: "Email on a schedule" }));
    const form = await screen.findByRole("form", { name: "Schedule Monthly revenue" });
    fireEvent.change(within(form).getByLabelText("File type"), { target: { value: "pdf" } });
    fireEvent.click(
      await within(form).findByRole("checkbox", { name: "Fin Ance (fin@example.com)" }),
    );
    fireEvent.click(within(form).getByRole("button", { name: "Schedule" }));
    await screen.findByText("No reports are emailed on a schedule yet.");
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      saved_report: "s1",
      frequency: "weekly",
      weekday: 0,
      time: "07:00",
      format: "pdf",
      recipients: ["u2"],
    });
  });
});
