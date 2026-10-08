import { render, screen } from "@testing-library/react";

import { App } from "./App";

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(body), {
          status,
          headers: {
            "Content-Type": status >= 400 ? "application/problem+json" : "application/json",
          },
        }),
    ),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("asks unauthenticated users to sign in", async () => {
    mockFetch(403, {
      type: "https://docs.tutortrack.app/problems/not-authenticated",
      title: "Authentication credentials were not provided.",
      status: 403,
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("renders the shell and enabled features for signed-in users", async () => {
    mockFetch(200, { features: { courses: true, payroll: false } });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Welcome" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByText("courses")).toBeInTheDocument();
    expect(screen.queryByText("payroll")).not.toBeInTheDocument();
  });
});
