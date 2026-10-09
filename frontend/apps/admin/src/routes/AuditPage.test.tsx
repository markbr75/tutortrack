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
});
