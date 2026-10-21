import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const USER = {
  ...ME,
  permissions: {
    ...ME.permissions,
    "reporting.dashboard.view": "all",
    "reporting.operations.view": "all",
    "reporting.builder.use": "all",
    "reporting.export": "all",
    "reporting.schedule.manage": "all",
  },
};

const BASE = {
  "GET /api/v1/me": { body: USER },
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};

const LESSONS_DEF = {
  key: "lessons",
  title: "Lessons by status",
  category: "operations",
  category_label: "Operations",
  description: "Lessons and hours by status.",
  filters: ["branch", "custom_field"],
  custom_field_entities: ["student", "tutor"],
  group_by: [{ value: "status", label: "Status" }],
  period: true,
  default_period: "this_month",
};

describe("reporting gap G5", () => {
  it("filters a lesson report on a student's custom field", async () => {
    window.history.pushState(null, "", "/analytics/lessons");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/reporting/reports": { body: [LESSONS_DEF] },
      "GET /api/v1/reporting/reports/lessons": (_body, url) => ({
        body: {
          report: LESSONS_DEF,
          params: Object.fromEntries(url.searchParams.entries()),
          period: { from: "2026-10-01", to: "2026-10-31" },
          columns: [
            { key: "group", label: "Status", type: "text" },
            { key: "lessons", label: "Lessons", type: "count" },
          ],
          rows: [{ group: "Completed", lessons: 2 }],
          totals: [{ lessons: 2 }],
          chart: null,
          notes: [],
          generated_at: "2026-10-21T09:00:00Z",
        },
      }),
      "GET /api/v1/custom-fields": (_body, url) => ({
        body:
          url.searchParams.get("entity_type") === "people.student"
            ? [{ id: "f1", entity_type: "people.student", key: "year_group", label: "Year group", type: "text", active: true }]
            : [{ id: "f2", entity_type: "people.tutor", key: "contract", label: "Contract", type: "text", active: true }],
      }), // prettier-ignore
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Lessons by status" })).toBeInTheDocument();
    const filter = screen.getByRole("group", { name: "Custom field filter" });
    expect(within(filter).getByLabelText("Custom field of")).toHaveValue("student");
    const field = within(filter).getByLabelText("Student custom field");
    await within(field).findByRole("option", { name: "Year group" });
    fireEvent.change(field, { target: { value: "year_group" } });
    const value = within(filter).getByLabelText("Equals");
    fireEvent.change(value, { target: { value: "Y10" } });
    fireEvent.blur(value);
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.path === "/api/v1/reporting/reports/lessons" &&
            new URLSearchParams(c.search).get("custom_field") === "student.year_group=Y10",
        ),
      ).toBe(true),
    );
    fireEvent.change(within(filter).getByLabelText("Custom field of"), {
      target: { value: "tutor" },
    });
    expect(
      await within(within(filter).getByLabelText("Tutor custom field")).findByRole("option", {
        name: "Contract",
      }),
    ).toBeInTheDocument();
  });

  it("schedules a saved custom report from the builder", async () => {
    window.history.pushState(null, "", "/analytics/builder");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/reporting/builder/datasets": { body: [] },
      "GET /api/v1/custom-reports": {
        body: {
          results: [
            { id: "r1", name: "Lessons by status", description: "", dataset: "lessons",
              definition: {}, shared: false, owner_name: "Sam", is_mine: true,
              created_at: "2026-10-14T10:00:00Z", updated_at: "2026-10-14T10:00:00Z" },
          ],
          next: null, previous: null,
        },
      }, // prettier-ignore
      "GET /api/v1/scheduled-reports/recipients": {
        body: [{ id: "u2", name: "Cora Ordinator", email: "cora@example.com" }],
      },
      "POST /api/v1/scheduled-reports": { status: 201, body: { id: "x1" } },
    });
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Email on a schedule: Lessons by status" }),
    );
    const form = await screen.findByRole("form", { name: "Schedule Lessons by status" });
    fireEvent.change(within(form).getByLabelText("How often"), { target: { value: "monthly" } });
    fireEvent.click(
      await within(form).findByRole("checkbox", { name: "Cora Ordinator (cora@example.com)" }),
    );
    fireEvent.click(within(form).getByRole("button", { name: "Schedule" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Lessons by status will be emailed on its schedule.",
    );
    const body = calls.find((c) => c.method === "POST")?.body as Record<string, unknown>;
    expect(body).toMatchObject({ custom_report: "r1", frequency: "monthly", recipients: ["u2"] });
    expect(body).not.toHaveProperty("saved_report");
  });
});
