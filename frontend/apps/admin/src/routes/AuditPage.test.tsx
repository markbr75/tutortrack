import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

describe("AuditPage", () => {
  it("searches the audit log and exports with the same filters", async () => {
    window.history.pushState(null, "", "/audit");
    const calls = mockApi({
      "GET /api/v1/me": {
        body: { ...ME, permissions: { "audit.view": "all", "audit.export": "all" } },
      },
      "GET /api/v1/organisation": { body: { status: "active" } },
      "GET /api/v1/me/organisations": { body: [] },
      "GET /api/v1/audit": { body: { results: [], next: null } },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Who"), {
      target: { value: "coord@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.path === "/api/v1/audit").length).toBeGreaterThan(1),
    );
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      "/api/v1/audit/export?actor_email=coord%40example.com",
    );
  });

  it("shows readable labels, and falls back to the codes when a label is missing", async () => {
    window.history.pushState(null, "", "/audit");
    const entry = {
      object_id: "01a13c73-be4e-728d-8dab-387399f8d864",
      changes: {},
      actor: null,
      actor_email: null,
      impersonator: null,
      ip: null,
      request_id: "",
      created_at: "2026-10-21T09:30:00Z",
    };
    mockApi({
      "GET /api/v1/me": { body: { ...ME, permissions: { "audit.view": "all" } } },
      "GET /api/v1/organisation": { body: { status: "active" } },
      "GET /api/v1/me/organisations": { body: [] },
      "GET /api/v1/audit": {
        body: {
          results: [
            {
              ...entry,
              id: "e1",
              action: "status_change",
              action_label: "Status changed",
              object_type: "scheduling.lessonseries",
              record_type_label: "Lesson series",
              object_repr: "LessonSeries object (01a13c73-be4e-728d-8dab-387399f8d864)",
              record_label: "Lesson series #f8d864",
            },
            {
              ...entry,
              id: "e2",
              action: "write_off",
              object_type: "billing.invoice",
              object_repr: "INV-0042",
            },
          ],
          next: null,
        },
      },
    });
    render(<App />);
    expect(await screen.findByText("Lesson series #f8d864")).toBeInTheDocument();
    expect(screen.getByText("Status changed")).toBeInTheDocument();
    expect(screen.getByText("Lesson series")).toBeInTheDocument();
    expect(screen.queryByText(/LessonSeries object/)).not.toBeInTheDocument();
    // No labels in the response: the translated action, the humanised type, the description.
    expect(screen.getByText("Written off")).toBeInTheDocument();
    expect(screen.getByText("Invoice")).toBeInTheDocument();
    expect(screen.getByText("INV-0042")).toBeInTheDocument();
  });
});
