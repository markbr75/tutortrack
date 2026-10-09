import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

function stubLocation(search: string) {
  const assign = vi.fn();
  vi.stubGlobal("location", { ...window.location, assign, pathname: "/login", search });
  window.history.pushState(null, "", `/login${search}`);
  return assign;
}

function fill() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "sam@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("LoginPage", () => {
  it("signs in and returns to the requested page", async () => {
    const assign = stubLocation("?next=%2Fteam");
    const calls = mockApi({
      "GET /api/v1/auth/sso/providers": {
        body: [{ key: "google", start_url: "https://app.x/api/v1/auth/sso/google/start" }],
      },
      "POST /api/v1/auth/login": { body: { mfa_required: false, user: { id: "u1" } } },
    });
    render(<App />);
    expect(
      await screen.findByRole("link", { name: "Continue with Google" }),
    ).toHaveAttribute("href", "https://app.x/api/v1/auth/sso/google/start?next=%2Fteam");
    fill();
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/team"));
    expect(calls.find((c) => c.path === "/api/v1/auth/login")?.body).toEqual({
      email: "sam@example.com",
      password: "secret",
      remember: false,
    });
  });

  it("asks for the second factor when the account has 2FA", async () => {
    const assign = stubLocation("");
    const calls = mockApi({
      "GET /api/v1/auth/sso/providers": { body: [] },
      "POST /api/v1/auth/login": { body: { mfa_required: true, user: null } },
      "POST /api/v1/auth/mfa/verify": { body: { id: "u1" } },
    });
    render(<App />);
    await screen.findByLabelText("Email");
    fill();
    fireEvent.change(await screen.findByLabelText("Code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
    expect(calls.find((c) => c.path === "/api/v1/auth/mfa/verify")?.body).toEqual({
      code: "123456",
    });
  });

  it("ignores off-site next parameters", async () => {
    const assign = stubLocation("?next=%2F%2Fevil.example");
    mockApi({
      "GET /api/v1/auth/sso/providers": { body: [] },
      "POST /api/v1/auth/login": { body: { mfa_required: false, user: { id: "u1" } } },
    });
    render(<App />);
    await screen.findByLabelText("Email");
    fill();
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
  });

  it("shows the API error for bad credentials", async () => {
    stubLocation("");
    mockApi({
      "GET /api/v1/auth/sso/providers": { body: [] },
      "POST /api/v1/auth/login": {
        status: 400,
        body: { type: "authentication-failed", title: "Incorrect email or password", status: 400 },
      },
    });
    render(<App />);
    await screen.findByLabelText("Email");
    fill();
    expect(await screen.findByText("Incorrect email or password")).toBeInTheDocument();
  });
});
