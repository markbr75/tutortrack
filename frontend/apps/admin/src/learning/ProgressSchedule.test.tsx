import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const page = (results: unknown[]) => ({ body: { results, next: null, previous: null } });

describe("scheduled progress reports (gap G5c, FR-21-6)", () => {
  it("turns on termly drafting from the progress reports tab", async () => {
    window.history.pushState(null, "", "/learning");
    const calls = mockApi({
      "GET /api/v1/me": {
        body: {
          ...ME,
          permissions: {
            ...ME.permissions,
            "learning.homework.view": "all",
            "learning.progress.write": "all",
            "learning.progress.approve": "all",
            "org.settings.manage": "all",
          },
        },
      },
      "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
      "GET /api/v1/me/organisations": { body: [] },
      "GET /api/v1/students": page([]),
      "GET /api/v1/learning/quizzes": page([]),
      "GET /api/v1/learning/homework": page([]),
      "GET /api/v1/learning/homework-assignments": page([]),
      "GET /api/v1/learning/progress-reports": page([]),
      "GET /api/v1/settings/learning": {
        body: {
          area: "learning",
          values: { "learning.progress_schedule": "none" },
          overrides: [],
          schema: [
            {
              key: "learning.progress_schedule",
              type: "choice",
              label: "Draft progress reports automatically",
              choices: [
                { value: "none", label: "Don't draft automatically" },
                { value: "monthly", label: "Every month" },
                { value: "termly", label: "At the end of each term" },
              ],
            },
          ],
        },
      },
      "PATCH /api/v1/settings/learning": (body) => ({
        body: { area: "learning", values: (body as { values: object }).values, schema: [] },
      }),
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Progress reports" }));
    expect(
      await screen.findByRole("heading", { name: "Draft reports automatically" }),
    ).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("Draft progress reports automatically"), {
      target: { value: "termly" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
        values: { "learning.progress_schedule": "termly" },
      }),
    );
  });
});
