import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const INVITATION = {
  email: "nia@example.com",
  role: "tutor",
  organisation_name: "Bright Minds",
  account_exists: false,
  expires_at: "2026-10-20T00:00:00Z",
};

describe("AcceptInvitePage", () => {
  it("creates an account and joins", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      assign,
      pathname: "/accept-invite",
      search: "?token=tok",
    });
    window.history.pushState(null, "", "/accept-invite?token=tok");
    const calls = mockApi({
      "GET /api/v1/me": { status: 403, body: { type: "x", title: "x", status: 403 } },
      "GET /api/v1/invitations/lookup": { body: INVITATION },
      "POST /api/v1/invitations/accept": { status: 201, body: { id: "m1", role: "tutor" } },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Join Bright Minds" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("First name"), { target: { value: "Nia" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long-pass-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
    expect(calls.find((c) => c.path === "/api/v1/invitations/accept")?.body).toMatchObject({
      token: "tok",
      first_name: "Nia",
      password: "long-pass-1",
    });
  });

  it("asks existing users to sign in first", async () => {
    window.history.pushState(null, "", "/accept-invite?token=tok");
    mockApi({
      "GET /api/v1/me": { status: 403, body: { type: "x", title: "x", status: 403 } },
      "GET /api/v1/invitations/lookup": { body: { ...INVITATION, account_exists: true } },
    });
    render(<App />);
    expect(await screen.findByText(/Sign in as nia@example.com/)).toBeInTheDocument();
  });

  it("explains invalid links", async () => {
    window.history.pushState(null, "", "/accept-invite?token=bad");
    mockApi({
      "GET /api/v1/me": { status: 403, body: { type: "x", title: "x", status: 403 } },
      "GET /api/v1/invitations/lookup": { status: 404, body: { type: "x", title: "x", status: 404 } },
    });
    render(<App />);
    expect(await screen.findByText(/invalid or has expired/)).toBeInTheDocument();
  });
});
