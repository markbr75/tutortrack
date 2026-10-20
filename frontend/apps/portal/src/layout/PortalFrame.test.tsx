import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

/** A phone: narrow, so the shell shows the tab bar rather than the rail. */
function phone(wide = false) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: wide,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

const LESSON = {
  id: "l1",
  title: "Maths group",
  start: new Date(Date.now() + 26 * 3600_000).toISOString(),
  end: new Date(Date.now() + 27 * 3600_000).toISOString(),
  timezone: "Europe/London",
  status: "planned",
  online: false,
  meeting_url: "",
  location: "Centre",
  notes_for_client: "",
  tutors: [{ name: "Nia Adeyemi", email: "", phone: "" }],
  students: [{ id: "s1", name: "Arjun Patel", outcome: "" }],
};

function family() {
  return mockApi({
    "GET /api/v1/me": {
      body: { user: { first_name: "Priya", last_name: "Patel", email: "priya@example.com" } },
    },
    "GET /api/v1/portal/me": {
      body: {
        role: "client",
        organisation: { name: "Bright Minds", primary_colour: "" },
        clients: [{ id: "c1", name: "The Patels" }],
        students: [{ id: "s1", name: "Arjun Patel" }],
        features: { invoices: true, reports: true, profile: true },
        welcome_text: "",
        help_url: "",
        terms_url: "",
      },
    },
    "GET /api/v1/portal/dashboard": {
      body: {
        next_lesson: LESSON,
        upcoming: [],
        reports: [],
        announcements: [],
        amount_due: { amount: "0.00", currency: "GBP" },
        credit: { amount: "0.00", currency: "GBP" },
      },
    },
    "GET /api/v1/portal/invoices": { body: { results: [], next: null } },
  });
}

describe("portal frame", () => {
  it("puts four everyday places in the tab bar and the rest under More", async () => {
    phone();
    family();
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Portal menu" });
    const tabs = within(nav)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(tabs).toEqual(["Home", "Lessons", "Payments", "Reports"]);
    expect(within(nav).getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");

    fireEvent.click(within(nav).getByRole("button", { name: "More" }));
    const sheet = await screen.findByRole("dialog", { name: "More" });
    expect(within(sheet).getByRole("heading", { name: "Lessons and learning" })).toBeVisible();
    expect(within(sheet).getByRole("link", { name: "Recordings" })).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: "Your data" })).toBeInTheDocument();
    expect(within(sheet).queryByRole("link", { name: "Lessons" })).not.toBeInTheDocument();

    fireEvent.click(within(sheet).getByRole("link", { name: "Details" }));
    expect(await screen.findByRole("button", { name: "More" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("shows every place in the rail on a wide screen, and signs out from the account menu", async () => {
    phone(true);
    const calls = family();
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Portal menu" });
    expect(within(nav).getByRole("link", { name: "Recordings" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "More" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Your account: Priya Patel" }));
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await vi.waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/api/v1/auth/logout")).toBe(true),
    );
  });
});
