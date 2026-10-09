import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const MEMBERS = {
  results: [
    { id: "m1", role: "admin", user: { id: "u1", name: "Sam", email: "sam@example.com" } },
    { id: "m2", role: "tutor", user: { id: "u2", name: "Nia", email: "nia@example.com" } },
  ],
};

const base = {
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
  "GET /api/v1/memberships": { body: MEMBERS },
  "GET /api/v1/invitations": { body: { results: [] } },
};

describe("TeamPage", () => {
  it("lists members and invites someone", async () => {
    window.history.pushState(null, "", "/team");
    const calls = mockApi({
      ...base,
      "GET /api/v1/me": {
        body: {
          ...ME,
          permissions: {
            "team.view": "all",
            "team.invite": "all",
            "team.manage": "all",
            "impersonation.start": "all",
          },
        },
      },
      "POST /api/v1/invitations": { status: 201, body: { id: "i1", email: "new@example.com" } },
    });
    render(<App />);
    expect(await screen.findByText("nia@example.com")).toBeInTheDocument();
    // Can change others' roles but not your own; "View as" only for tutors/clients/students.
    expect(screen.getByLabelText("Role: Nia")).toHaveValue("tutor");
    expect(screen.queryByLabelText("Role: Sam")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "View as" })).toHaveLength(1);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
    expect(await screen.findByText("Invitation sent to new@example.com.")).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path === "/api/v1/invitations")?.body).toEqual(
        { email: "new@example.com", role: "tutor" },
      ),
    );
  });

  it("is read-only without team.manage and team.invite", async () => {
    window.history.pushState(null, "", "/team");
    mockApi({ ...base, "GET /api/v1/me": { body: ME } });
    render(<App />);
    expect(await screen.findByText("nia@example.com")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send invitation" })).not.toBeInTheDocument();
  });
});
