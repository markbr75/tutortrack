import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";
import { flush, routePattern, setOrganisationAllowsAnalytics, track } from "./analytics";
import { Markdown } from "./Markdown";
import { Tour } from "./Tour";

type Routes = Parameters<typeof mockApi>[0];

const ORG = { id: "o1", name: "Bright Minds", slug: "brightminds", status: "active" };

const GUIDANCE = {
  completed_tours: ["welcome"],
  dismissed_tours: [],
  changelog_unread: 0,
  nps_due: false,
  support_unread: 0,
  analytics_allowed: true,
};

const CHECKLIST = {
  steps: [
    { key: "service", title: "Set up a service", link: "/catalogue", done: true, completed_at: "2026-10-01T10:00:00Z" },
    { key: "student", title: "Add a student", link: "/students", done: false, completed_at: null },
    { key: "lesson", title: "Schedule a lesson", link: "/calendar", done: false, completed_at: null },
    { key: "payments", title: "Connect Stripe", link: "/settings/payments", done: false, completed_at: null },
    { key: "invoice", title: "Send your first invoice", link: "/billing", done: false, completed_at: null },
  ],
  done: 1,
  total: 5,
  completed_at: null,
  dismissed_at: null,
}; // prettier-ignore

function shell(extra: Routes = {}, me = ME): Routes {
  return {
    "GET /api/v1/me": { body: me },
    "GET /api/v1/organisation": { body: ORG },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/me/guidance": { body: GUIDANCE },
    "GET /api/v1/setup-checklist": { body: CHECKLIST },
    ...extra,
  };
}

function clearConsent() {
  document.cookie = "tt_consent=; Max-Age=0; Path=/";
}

afterEach(() => {
  vi.unstubAllGlobals();
  clearConsent();
  window.history.pushState(null, "", "/");
});

describe("setup checklist", () => {
  it("shows progress and links to the steps still to do", async () => {
    const me = { ...ME, permissions: { ...ME.permissions, "success.checklist.manage": "all" } };
    const calls = mockApi(
      shell(
        {
          "PATCH /api/v1/setup-checklist": {
            body: { ...CHECKLIST, dismissed_at: "2026-10-14T10:00:00Z" },
          },
        },
        me,
      ),
    );
    render(<App />);
    const region = await screen.findByRole("region", { name: "Get started" });
    expect(within(region).getByText("1 of 5 done")).toBeInTheDocument();
    // Progress reads in words (no bar).
    expect(within(region).queryByRole("progressbar")).toBeNull();
    expect(within(region).getByRole("link", { name: "Add a student" })).toHaveAttribute(
      "href",
      "/students",
    );
    expect(within(region).queryByRole("link", { name: "Set up a service" })).toBeNull();
    fireEvent.click(within(region).getByRole("button", { name: "Hide checklist" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Get started" })).toBeNull());
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ dismissed: true });
  });
});

describe("help panel", () => {
  it("suggests and searches articles and opens one", async () => {
    window.history.pushState(null, "", "/");
    const calls = mockApi(
      shell({
        "GET /api/v1/help/articles": (_body, url) => ({
          body: url.searchParams.get("q")
            ? [{ slug: "send-invoices", title: "Make and send invoices", summary: "", tour: "billing" }]
            : [{ slug: "getting-started", title: "Getting started with TutorTrack", summary: "Five steps", tour: "welcome" }],
        }),
        "GET /api/v1/help/articles/send-invoices": {
          body: {
            slug: "send-invoices", title: "Make and send invoices", summary: "", tour: "billing",
            routes: ["/billing"], tags: [],
            body: "Completed lessons become **charges**.\n\n1. Go to Billing.\n2. Issue it.",
          },
        },
      }),
    ); // prettier-ignore
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Help" }));
    const dialog = await screen.findByRole("dialog", { name: "Help" });
    expect(await within(dialog).findByText("Getting started with TutorTrack")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByRole("searchbox", { name: "Search help" }), {
      target: { value: "invoice" },
    });
    fireEvent.click(await within(dialog).findByText("Make and send invoices"));
    expect(await within(dialog).findByRole("heading", { name: "Make and send invoices" }));
    expect(within(dialog).getByText("charges").tagName).toBe("STRONG");
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(2);
    expect(calls.some((c) => c.search.includes("route=%2F"))).toBe(true);
  });

  it("links to the full guide's section about this page", async () => {
    window.history.pushState(null, "", "/tutors");
    mockApi(
      shell({
        "GET /api/v1/help/articles": { body: [] },
        "GET /guides/routes.json": {
          body: [
            { guide: "user-guide.html", id: "people-lists", routes: ["admin:/tutors"] },
            { guide: "admin-guide.html", id: "plan", routes: ["admin:/settings/plan"] },
          ],
        },
        "GET /api/v1/tutors": { body: { results: [], next: null, previous: null } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Help" }));
    const dialog = await screen.findByRole("dialog", { name: "Help" });
    const page = await within(dialog).findByRole("link", {
      name: "Read about this page in the user guide (opens in a new tab)",
    });
    expect(page).toHaveAttribute("href", "/guides/user-guide.html#people-lists");
    expect(page).toHaveAttribute("target", "_blank");
    expect(
      within(dialog).getByRole("link", { name: /Admin guide: setup, settings and the console/ }),
    ).toHaveAttribute("href", "/guides/admin-guide.html");
  });

  it("sends a question to support", async () => {
    const me = { ...ME, permissions: { ...ME.permissions, "success.support.chat": "own" } };
    const calls = mockApi(
      shell(
        {
          "GET /api/v1/help/articles": { body: [] },
          "GET /api/v1/support-conversations": { body: { results: [], next: null, previous: null } },
          "POST /api/v1/support-conversations": {
            status: 201,
            body: {
              id: "c1", subject: "Invoices", status: "open", page: "/", opened_by_name: "Sam",
              last_message_at: "2026-10-14T10:00:00Z", customer_unread: false, closed_at: null,
              created_at: "2026-10-14T10:00:00Z", csat_score: null,
              messages: [{ id: "m1", from_support: false, author_name: "Sam", body: "How?", created_at: "2026-10-14T10:00:00Z" }],
            },
          },
          "GET /api/v1/support-conversations/c1": {
            body: {
              id: "c1", subject: "Invoices", status: "answered", page: "/", opened_by_name: "Sam",
              last_message_at: "2026-10-14T10:00:00Z", customer_unread: false, closed_at: null,
              created_at: "2026-10-14T10:00:00Z", csat_score: null,
              messages: [
                { id: "m1", from_support: false, author_name: "Sam", body: "How?", created_at: "2026-10-14T10:00:00Z" },
                { id: "m2", from_support: true, author_name: "Pat (TutorTrack)", body: "Like this.", created_at: "2026-10-14T10:05:00Z" },
              ],
            },
          },
        },
        me,
      ),
    ); // prettier-ignore
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Help" }));
    const dialog = await screen.findByRole("dialog", { name: "Help" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "Chat with support" }));
    fireEvent.change(await within(dialog).findByLabelText("Your question"), {
      target: { value: "How?" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    expect(await within(dialog).findByText("Like this.")).toBeInTheDocument();
    const post = calls.find(
      (c) => c.method === "POST" && c.path === "/api/v1/support-conversations",
    );
    expect(post?.body).toMatchObject({ body: "How?", page: "/" });
    // Answered chats can be rated (CSAT).
    expect(within(dialog).getByRole("group", { name: /How satisfied/ })).toBeInTheDocument();
  });
});

describe("NPS prompt", () => {
  it("asks once due, without taking focus, and sends the score", async () => {
    const calls = mockApi(
      shell({
        "GET /api/v1/me/guidance": { body: { ...GUIDANCE, nps_due: true } },
        "POST /api/v1/surveys/responses": {
          status: 201,
          body: { id: "r1", kind: "nps", score: 9, comment: "", topic: "", created_at: "" },
        },
      }),
    );
    render(<App />);
    const group = await screen.findByRole("group", { name: /How likely are you to recommend/ });
    expect(document.activeElement).not.toBe(within(group).getByRole("radio", { name: "9" }));
    fireEvent.click(within(group).getByRole("radio", { name: "9" }));
    fireEvent.change(screen.getByLabelText(/main reason/), { target: { value: "Fast" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Thank you for your feedback.")).toBeInTheDocument();
    const post = calls.find((c) => c.path === "/api/v1/surveys/responses");
    expect(post?.body).toEqual({ kind: "nps", score: 9, comment: "Fast" });
  });

  it("can be put off", async () => {
    const calls = mockApi(
      shell({
        "GET /api/v1/me/guidance": { body: { ...GUIDANCE, nps_due: true } },
        "POST /api/v1/surveys/responses": { status: 201, body: {} },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Not now" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Not now" })).toBeNull());
    expect(calls.find((c) => c.path === "/api/v1/surveys/responses")?.body).toMatchObject({
      score: null,
    });
  });
});

describe("product tour", () => {
  function renderTour(onFinish = vi.fn()) {
    document.body.innerHTML = "";
    const target = document.createElement("div");
    target.dataset.tour = "help";
    document.body.appendChild(target);
    const tour = {
      key: "welcome",
      path: "/",
      steps: [{ key: "intro" }, { key: "help", target: "[data-tour='help']" }],
    };
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Tour tour={tour} onFinish={onFinish} />
      </QueryClientProvider>,
    );
    return { target, onFinish };
  }

  it("moves focus to each step, highlights its element and finishes", () => {
    const { target, onFinish } = renderTour();
    const dialog = screen.getByRole("dialog", { name: "Welcome to TutorTrack" });
    expect(dialog).toHaveAttribute("aria-modal", "false");
    expect(screen.getByText("Step 1 of 2")).toBeInTheDocument();
    expect(document.activeElement).toBe(
      screen.getByRole("heading", { name: "Welcome to TutorTrack" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Step 2 of 2")).toBeInTheDocument();
    expect(target.classList.contains("outline")).toBe(true);
    expect(document.activeElement).toBe(
      screen.getByRole("heading", { name: "Help is always here" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onFinish).toHaveBeenCalledWith("completed");
  });

  it("closes on Escape", () => {
    const { onFinish } = renderTour();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onFinish).toHaveBeenCalledWith("dismissed");
  });
});

describe("product analytics", () => {
  it("turns record ids into patterns", () => {
    expect(routePattern("/clients/0190f2a4-1b2c-7d3e-8f40-123456789abc/billing")).toBe(
      "/clients/$id/billing",
    );
    expect(routePattern("/students/42?tab=x")).toBe("/students/$id");
  });

  it("sends nothing without consent, and batches with it", async () => {
    const calls = mockApi({
      "POST /api/v1/analytics/events": { status: 202, body: { accepted: 1 } },
    });
    setOrganisationAllowsAnalytics(true);
    track("page.viewed", undefined, "/billing");
    await flush();
    expect(calls).toHaveLength(0);
    document.cookie = `tt_consent=${encodeURIComponent(
      JSON.stringify({ necessary: true, analytics: true, marketing: false, version: 1 }),
    )}; Path=/`;
    track("page.viewed", { tab: "x" }, "/billing");
    await flush();
    expect(calls).toHaveLength(1);
    expect(calls[0]!.body).toMatchObject({
      events: [{ name: "page.viewed", route: "/billing", properties: { tab: "x" } }],
    });
    setOrganisationAllowsAnalytics(false);
    track("page.viewed", undefined, "/billing");
    await flush();
    expect(calls).toHaveLength(1);
  });
});

describe("markdown", () => {
  it("renders the help subset without unsafe links", () => {
    render(
      <Markdown
        source={"# Title\n\n- one\n- **two**\n\n[ok](/billing) [bad](javascript:alert(1))"}
      />,
    );
    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "ok" })).toHaveAttribute("href", "/billing");
    expect(screen.queryByRole("link", { name: "bad" })).toBeNull();
  });
});
