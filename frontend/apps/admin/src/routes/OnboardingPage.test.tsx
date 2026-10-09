import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const STEPS = ["business", "locale", "branding", "service", "students", "payments", "invoicing"];

function state(current: string, done: string[] = []) {
  return {
    current_step: current,
    completed_at: null,
    answers: {},
    steps: STEPS.map((key) => ({ key, status: done.includes(key) ? "completed" : "pending" })),
  };
}

describe("OnboardingPage", () => {
  it("exchanges the handoff token, then walks through steps", async () => {
    window.history.pushState(null, "", "/onboarding?handoff=tok");
    const calls = mockApi({
      "POST /api/v1/auth/handoff": { body: { id: "u1", email: "a@b.c", email_verified: false } },
      "GET /api/v1/onboarding/state": { body: state("business") },
      "POST /api/v1/onboarding/business": { body: state("locale", ["business"]) },
    });
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Your business" })).toBeInTheDocument();
    expect(calls[0]).toMatchObject({ method: "POST", path: "/api/v1/auth/handoff" });
    expect(window.location.search).toBe(""); // token removed from the address bar
    expect(screen.getByText("Step 1 of 7")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Type of business"), { target: { value: "team" } });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(
      await screen.findByRole("heading", { name: "Language, currency and timezone" }),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/onboarding/business")?.body).toEqual({
      business_type: "team",
      team_size: "1",
    });
  });

  it("can skip a step", async () => {
    window.history.pushState(null, "", "/onboarding");
    const calls = mockApi({
      "GET /api/v1/onboarding/state": { body: state("business") },
      "POST /api/v1/onboarding/business": { body: state("locale") },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Skip for now" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/onboarding/business")?.body).toEqual({
        skip: true,
      }),
    );
  });

  it("explains an expired handoff link", async () => {
    window.history.pushState(null, "", "/onboarding?handoff=old");
    mockApi({
      "POST /api/v1/auth/handoff": {
        status: 400,
        body: { type: "invalid-token", title: "Expired", status: 400 },
      },
    });
    render(<App />);
    expect(await screen.findByText(/sign-in link has expired/)).toBeInTheDocument();
  });
});
