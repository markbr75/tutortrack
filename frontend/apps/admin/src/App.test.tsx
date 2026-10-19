import { fireEvent, render, screen, within } from "@testing-library/react";

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
      "GET /api/v1/me": {
        body: {
          ...ME,
          permissions: { ...ME.permissions, "people.client.view": "all" },
          features: { courses: true, payroll: false },
        },
      },
      "GET /api/v1/organisation": { body: ORG },
      "GET /api/v1/me/organisations": { body: [] },
    });
    render(<App />);
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: /^Good (morning|afternoon|evening), Sam$/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByText("Courses and group programmes")).toBeInTheDocument();
    expect(screen.queryByText("Tutor payroll and expenses")).not.toBeInTheDocument();
    // The sidebar is grouped by job, and settings live under one Settings entry.
    const main = screen.getByRole("navigation", { name: "Main" });
    expect(within(main).getByRole("region", { name: "People" })).toBeInTheDocument();
    expect(within(main).queryByRole("link", { name: "Team" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("collapses a long menu to its groups, keeps the current one open and counts what needs marking", async () => {
    window.localStorage.removeItem("tt.nav.open");
    window.history.pushState(null, "", "/clients");
    const permissions = Object.fromEntries(
      [
        "people.client.view",
        "people.student.view",
        "people.tutor.view",
        "people.merge",
        "crm.task.view",
        "scheduling.lesson.view",
        "scheduling.lesson.complete",
        "scheduling.availability.view",
        "scheduling.lesson.edit",
        "jobs.job.view",
        "matching.search",
        "delivery.report.view",
        "delivery.feedback.view",
        "courses.view",
        "billing.invoice.view",
        "payroll.view",
        "leads.enquiry.view",
        "comms.inbox.view",
      ].map((p) => [p, "all"]),
    );
    mockApi({
      "GET /api/v1/me": { body: { ...ME, permissions } },
      "GET /api/v1/organisation": { body: ORG },
      "GET /api/v1/me/organisations": { body: [] },
      "GET /api/v1/unconfirmed-lessons": { body: [{ id: "u1" }, { id: "u2" }, { id: "u3" }] },
    });
    render(<App />);
    const main = await screen.findByRole("navigation", { name: "Main" });
    // The current page's group is open; the others show only their heading.
    expect(within(main).getByRole("button", { name: "People" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(within(main).getByRole("link", { name: "Clients" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    const money = within(main).getByRole("button", { name: "Money" });
    expect(money).toHaveAttribute("aria-expanded", "false");
    expect(within(main).queryByRole("link", { name: "Billing" })).not.toBeInTheDocument();
    fireEvent.click(money);
    expect(within(main).getByRole("link", { name: "Billing" })).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem("tt.nav.open") ?? "[]")).toContain("money");
    // People and Scheduling open on a first visit; the count reads on the link…
    const scheduling = within(main).getByRole("button", { name: "Scheduling" });
    expect(scheduling).toHaveAttribute("aria-expanded", "true");
    expect(
      await within(main).findByRole("link", { name: /^Unconfirmed lessons\s*3 waiting$/ }),
    ).toBeInTheDocument();
    // …and on the heading once its group is closed, so it is never hidden.
    fireEvent.click(scheduling);
    expect(within(main).getByRole("button", { name: /^Scheduling\s*3 waiting$/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    window.history.pushState(null, "", "/");
  });

  it("groups settings in their own menu, following permissions", async () => {
    window.history.pushState(null, "", "/team");
    mockApi({
      "GET /api/v1/me": { body: ME },
      "GET /api/v1/organisation": { body: ORG },
      "GET /api/v1/me/organisations": { body: [] },
    });
    render(<App />);
    const settings = await screen.findByRole("navigation", { name: "Settings" });
    expect(within(settings).getByRole("link", { name: "Team" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // No audit.view, so no audit link.
    expect(within(settings).queryByRole("link", { name: "Audit log" })).not.toBeInTheDocument();
    window.history.pushState(null, "", "/");
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
