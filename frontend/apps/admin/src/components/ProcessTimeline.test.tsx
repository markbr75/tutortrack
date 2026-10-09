import { render, screen } from "@testing-library/react";
import { createI18n, I18nextProvider } from "@tutortrack/i18n";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ME, mockApi } from "../test-utils";
import { ProcessTimeline } from "./ProcessTimeline";

afterEach(() => vi.unstubAllGlobals());

function renderTimeline() {
  render(
    <I18nextProvider i18n={createI18n("en-GB")}>
      <QueryClientProvider client={new QueryClient()}>
        <ProcessTimeline subjectType="organisation" subjectId="o1" />
      </QueryClientProvider>
    </I18nextProvider>,
  );
}

describe("ProcessTimeline", () => {
  it("lists a record's processes with their current step", async () => {
    const calls = mockApi({
      "GET /api/v1/me": { body: { ...ME, permissions: { "processes.view": "all" } } },
      "GET /api/v1/processes": {
        body: {
          results: [
            {
              id: "p1",
              process: "org-closure",
              status: "running",
              current_step: "grace_period",
              started_at: "2026-10-09T09:00:00Z",
            },
          ],
        },
      },
    });
    renderTimeline();
    expect(await screen.findByText("Account closure")).toBeInTheDocument();
    expect(screen.getByText(/In progress · Grace period/)).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/v1/processes")).toBe(true);
  });

  it("renders nothing without the permission", async () => {
    const calls = mockApi({ "GET /api/v1/me": { body: ME } });
    renderTimeline();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("Processes")).not.toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/v1/processes")).toBe(false);
  });
});
