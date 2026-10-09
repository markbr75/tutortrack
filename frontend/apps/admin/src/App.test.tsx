import { render, screen } from "@testing-library/react";

import { App } from "./App";
import { ME, mockApi } from "./test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const ORG = {
  id: "o1",
  name: "Bright Minds",
  slug: "brightminds",
  status: "active",
  has_demo_data: false,
};

describe("App", () => {
  it("sends unauthenticated users to the login page", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, pathname: "/", search: "" });
    mockApi({
      "GET /api/v1/me": {
        status: 403,
        body: { type: "not-authenticated", title: "Not signed in", status: 403 },
      },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(assign).toHaveBeenCalledWith("/login?next=%2F");
  });

  it("renders the shell and enabled features for signed-in users", async () => {
    mockApi({
      "GET /api/v1/me": { body: { ...ME, features: { courses: true, payroll: false } } },
      "GET /api/v1/organisation": { body: ORG },
      "GET /api/v1/me/organisations": { body: [] },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Welcome" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByText("courses")).toBeInTheDocument();
    expect(screen.queryByText("payroll")).not.toBeInTheDocument();
    // Navigation follows permissions: no audit.view, so no audit link.
    expect(screen.getByRole("link", { name: "Team" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Audit log" })).not.toBeInTheDocument();
  });

  it("shows the impersonation banner", async () => {
    mockApi({
      "GET /api/v1/me": {
        body: { ...ME, impersonator: { id: "a1", email: "a@x", name: "Admin", write: false } },
      },
      "GET /api/v1/organisation": { body: ORG },
      "GET /api/v1/me/organisations": { body: [] },
    });
    render(<App />);
    expect(await screen.findByText(/You're viewing as Sam/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop viewing as" })).toBeInTheDocument();
  });

  it("shows the organisation switcher and suspended banner", async () => {
    mockApi({
      "GET /api/v1/me": { body: ME },
      "GET /api/v1/organisation": { body: { ...ORG, status: "suspended" } },
      "GET /api/v1/me/organisations": {
        body: [
          { id: "o1", name: "Bright Minds", url: "https://brightminds.x", is_current: true },
          { id: "o2", name: "Other Tutors", url: "https://other.x", is_current: false },
        ],
      },
    });
    render(<App />);
    const switcher = await screen.findByRole("navigation", { name: "Switch organisation" });
    expect(switcher).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Other Tutors" })).toHaveAttribute(
      "href",
      "https://other.x",
    );
    expect(screen.getByRole("link", { name: /Bright Minds/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByText("Your account is suspended")).toBeInTheDocument();
  });
});
