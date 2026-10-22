import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "./App";
import { ME, mockApi } from "./test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const STAFF = {
  email: "pat@tutortrack.app",
  is_platform_staff: true,
  mfa_verified: true,
  network_allowed: true,
};

function platform(extra: Routes): Routes {
  return { "GET /api/v1/platform/me": { body: STAFF }, ...extra };
}

const OWNER = {
  ...ME,
  membership: { ...ME.membership, role: "owner" },
  permissions: {
    ...ME.permissions,
    "subscription.view": "all",
    "subscription.manage": "all",
    "sites.view": "all",
    "sites.site.manage": "all",
    "sites.site.publish": "all",
  },
};

function app(extra: Routes): Routes {
  return {
    "GET /api/v1/me": { body: OWNER },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    ...extra,
  };
}

describe("G6: platform console", () => {
  it("previews and sends a breach notice with a reason", async () => {
    window.history.pushState(null, "", "/platform/customer-notices");
    const notice = {
      id: "n1", kind: "breach", template: "breach", subject: "Incident", body: "Body",
      variables: {}, organisation_ids: [], status: "draft", reason: "", created_at: "2026-10-14T09:00:00Z",
      sent_at: null, organisations_count: 0, recipients_count: 0,
    }; // prettier-ignore
    const calls = mockApi(
      platform({
        "GET /api/v1/platform/customer-notices/templates": {
          body: [
            {
              key: "breach", title: "Personal data breach (72-hour notice)", kind: "breach",
              subject: "s", body: "b", variables: ["summary", "contact"],
            },
          ],
        },
        "GET /api/v1/platform/customer-notices": { body: [] },
        "POST /api/v1/platform/customer-notices": { status: 201, body: notice },
        "GET /api/v1/platform/customer-notices/n1/preview": {
          body: { subject: "Incident at Bright Minds", body: "A laptop was stolen.", organisations: 3 },
        },
        "POST /api/v1/platform/customer-notices/n1/send": { body: { ...notice, status: "sending" } },
      }),
    ); // prettier-ignore
    render(<App />);
    fireEvent.change(await screen.findByLabelText("What happened"), {
      target: { value: "A laptop was stolen." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText("Incident at Bright Minds")).toBeInTheDocument();
    expect(screen.getByText(/3 organisations/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send notice" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "INC-42" } });
    fireEvent.click(screen.getByRole("button", { name: "Send notice" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/n1/send"))?.body).toEqual({ reason: "INC-42" }),
    );
    const created = calls.find(
      (c) => c.method === "POST" && c.path === "/api/v1/platform/customer-notices",
    );
    expect(created?.body).toMatchObject({
      template: "breach",
      variables: { summary: "A laptop was stolen." },
    });
  });

  it("lists failed workflows with a Temporal link and terminates with a reason", async () => {
    window.history.pushState(null, "", "/platform/workflows");
    const row = {
      organisation_id: "00000000-0000-0000-0000-000000000001", organisation_name: "Bright Minds",
      workflow_id: "invoice-run:o1:r1", run_id: "", workflow_type: "InvoiceRunWorkflow",
      process: "invoice-run", subject_type: "", subject_id: "", status: "running",
      current_step: "collecting", started_at: "2026-10-14T09:00:00Z",
      updated_at: "2026-10-14T09:00:00Z", closed_at: null, last_error: "activity retrying",
      temporal_url: "http://localhost:8233/namespaces/tt/workflows/invoice-run%3Ao1%3Ar1",
    }; // prettier-ignore
    const calls = mockApi(
      platform({
        "GET /api/v1/platform/workflows": { body: { results: [row], next: null, previous: null } },
        [`POST /api/v1/platform/workflows/${row.organisation_id}/invoice-run%3Ao1%3Ar1`]: {
          body: { ...row, status: "terminated" },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByText("activity retrying")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in Temporal" })).toHaveAttribute(
      "href",
      row.temporal_url,
    );
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "INC-7" } });
    fireEvent.click(screen.getByRole("button", { name: "Terminate" }));
    await waitFor(() =>
      expect(
        calls.some((c) => c.method === "POST" && c.path.includes("/platform/workflows/")),
      ).toBe(true),
    );
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({ action: "terminate", reason: "INC-7" });
  });

  it("edits a plan price", async () => {
    window.history.pushState(null, "", "/platform/plans");
    const calls = mockApi(
      platform({
        "GET /api/v1/platform/plans": {
          body: [
            {
              key: "solo", name: "Solo", description: "", visibility: "public", rank: 10,
              trial_days: 30, seat_mode: "delivered", entitlements: {},
              prices: [
                { id: 7, currency: "GBP", interval: "month", component: "base_fee",
                  unit_amount: "19.00", included_quantity: 0, stripe_price_id: "" },
              ],
            },
          ],
        },
        "PATCH /api/v1/platform/plans/solo/prices/7": { body: {} },
      }),
    ); // prettier-ignore
    render(<App />);
    const amount = await screen.findByLabelText("Amount for Base fee (month)");
    fireEvent.change(amount, { target: { value: "21.00" } });
    const row = amount.closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toMatchObject({ unit_amount: "21.00" }),
    );
  });

  it("reconciles revenue share and reports missing days", async () => {
    window.history.pushState(null, "", "/platform/revenue-share");
    const calls = mockApi(
      platform({
        "GET /api/v1/platform/revenue-share": {
          body: {
            month: "2026-10",
            totals: { GBP: { processed: "1200.00", reported: "1000.00", expected_fee: "18.00" } },
            rows: [
              {
                organisation_id: "o1", organisation_name: "Bright Minds", currency: "GBP",
                percent: "1.5", processed: "1200.00", reported: "1000.00", difference: "200.00",
                expected_fee: "18.00", reported_fee: "15.00", unreported_days: ["2026-10-12"],
                changed_days: [], ok: false,
              },
            ],
          },
        },
        "POST /api/v1/platform/revenue-share/report-missing": { body: { count: 1 } },
      }),
    ); // prettier-ignore
    render(<App />);
    expect(await screen.findByText("1 day not reported")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Report missing days" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/report-missing"))?.body).toMatchObject({
        organisation_id: "o1",
      }),
    );
  });

  it("filters tenants by MRR", async () => {
    window.history.pushState(null, "", "/platform");
    const calls = mockApi(
      platform({
        "GET /api/v1/platform/tenants": { body: { results: [], next: null, previous: null } },
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("MRR at least"), { target: { value: "50" } });
    await waitFor(() => expect(calls.some((c) => c.search.includes("mrr_min=50"))).toBe(true));
  });
});

describe("G6: organisation app", () => {
  it("deletes the account after showing what happens", async () => {
    window.history.pushState(null, "", "/account");
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, pathname: "/account", search: "" });
    const calls = mockApi(
      app({
        "GET /api/v1/me/account-deletion": {
          body: {
            organisations: [
              { organisation_id: "o1", name: "Bright Minds", role: "admin", outcome: "erased" },
            ],
            blockers: [],
            needs_password: true,
          },
        },
        "POST /api/v1/me/account-deletion": {
          body: { id: "d1", completed_at: "2026-10-14T10:00:00Z", organisations: [] },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete my account…" }));
    expect(await screen.findByText(/Bright Minds: your records there are erased/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Your password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/login?deleted=1"));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ password: "pw" });
  });

  it("explains why a last owner can't delete their account", async () => {
    window.history.pushState(null, "", "/account");
    mockApi(
      app({
        "GET /api/v1/me/account-deletion": {
          body: {
            organisations: [],
            blockers: [{ organisation_id: "o1", organisation_name: "Bright Minds", reason: "last_owner" }],
            needs_password: true,
          },
        },
      }),
    ); // prettier-ignore
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete my account…" }));
    expect(await screen.findByText(/only owner of Bright Minds/)).toBeVisible();
    expect(screen.queryByLabelText("Your password")).not.toBeInTheDocument();
  });

  it("buys an add-on after confirming", async () => {
    window.history.pushState(null, "", "/settings/plan");
    const addon = {
      key: "custom_domain", name: "Custom domain", description: "Your own domain.",
      feature: "custom_domain", price: { amount: "10.00", currency: "GBP" }, interval: "month",
      active: false, included_in_plan: false, started_at: null,
    }; // prettier-ignore
    const calls = mockApi(
      app({
        "GET /api/v1/subscription": {
          body: {
            plan: "solo", plan_name: "Solo", effective_plan: "solo", status: "active",
            interval: "month", currency: "GBP", trial_ends_at: null, current_period_end: null,
            pending_plan: null, pending_interval: "", cancel_at_period_end: false,
            past_due_since: null, has_payment_method: true, card: null, can_manage: true,
          },
        },
        "GET /api/v1/subscription/addons": { body: [addon] },
        "POST /api/v1/subscription/addons/custom_domain": {
          status: 201,
          body: { ...addon, active: true },
        },
      }),
    ); // prettier-ignore
    render(<App />);
    expect(await screen.findByText("£10.00 a month")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/custom_domain"))).toBe(
        true,
      ),
    );
  });

  it("writes and publishes a blog post", async () => {
    window.history.pushState(null, "", "/website?tab=blog");
    const post = {
      id: "p1", site: "s1", title: "Open day", slug: "open-day", excerpt: "", body: "",
      cover_image: null, author_name: "", status: "draft", published_at: null, seo_title: "",
      meta_description: "", url: "/blog/open-day", updated_at: "2026-10-14T10:00:00Z",
    }; // prettier-ignore
    const calls = mockApi(
      app({
        "GET /api/v1/sites/posts": { body: { results: [post], next: null, previous: null } },
        "POST /api/v1/sites/posts": { status: 201, body: post },
        "POST /api/v1/sites/posts/p1/publish": { body: { ...post, status: "published" } },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Open day")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/p1/publish"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "New post" }));
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Exam results" } });
    fireEvent.change(screen.getByLabelText("Post"), { target: { value: "Well done\n\nAll" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.method === "POST" && c.path === "/api/v1/sites/posts")?.body,
      ).toMatchObject({ title: "Exam results", body: "Well done\n\nAll" }),
    );
  });

  it("lets a family stop feedback requests from the survey page", async () => {
    window.history.pushState(null, "", "/feedback/tok");
    const shown = {
      organisation: "Bright Minds", student: "Arjun", tutor: "Nia", lesson: "Maths",
      lesson_date: "2026-10-13", status: "sent", expires_at: "2026-10-20T00:00:00Z", rating: null,
    }; // prettier-ignore
    const calls = mockApi({
      "GET /api/v1/public/lesson-feedback/tok": { body: shown },
      "POST /api/v1/public/lesson-feedback/tok": { body: { ...shown, status: "answered" } },
    });
    render(<App />);
    fireEvent.click(await screen.findByLabelText("4 stars"));
    fireEvent.click(screen.getByLabelText("Don't ask me for lesson feedback again"));
    fireEvent.click(screen.getByRole("button", { name: "Send feedback" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        rating: 4,
        stop_asking: true,
      }),
    );
  });
});
