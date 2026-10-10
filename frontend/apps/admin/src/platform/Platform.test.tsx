import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

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

const TENANT = {
  id: "o1", name: "Bright Minds", slug: "brightminds", status: "active", region: "uk",
  country: "GB", created_at: "2026-09-01T10:00:00Z", plan: "team",
  subscription_status: "active", trial_ends_at: null, last_activity: "2026-10-09T10:00:00Z",
  members: 3, mrr: { amount: "57.00", currency: "GBP" },
}; // prettier-ignore

const DETAIL = {
  organisation: {
    id: "o1", name: "Bright Minds", slug: "brightminds", status: "active",
    business_type: "agency", country: "GB", region: "uk", default_currency: "GBP",
    timezone: "Europe/London", contact_email: "", created_at: "2026-09-01T10:00:00Z",
    suspension_reason: "", closed_at: null, base_url: "https://brightminds.tutortrack.app",
  },
  subscription: {
    plan: "team", status: "active", interval: "month", currency: "GBP", trial_ends_at: null,
    current_period_end: null, pending_plan: null, cancel_at_period_end: false,
    cancellation_reason: "", stripe_customer_id: "cus_1", stripe_subscription_id: "sub_1",
    seats: 5,
  },
  overrides: [],
  usage: { max_tutors: 5 },
  members: [
    {
      id: "m1", email: "owner@example.com", name: "Olu Owner", role: "owner",
      status: "active", last_active_at: null, email_verified: true, has_mfa: false,
    },
  ],
  recent_errors: [],
  dead_letters: 0,
  audit: [],
}; // prettier-ignore

function platform(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/platform/me": { body: STAFF },
    "GET /api/v1/platform/tenants": { body: { results: [TENANT], next: null, previous: null } },
    "GET /api/v1/platform/tenants/o1": { body: DETAIL },
    ...extra,
  };
}

describe("platform console", () => {
  it("explains when the user can't use it", async () => {
    window.history.pushState(null, "", "/platform");
    mockApi({ "GET /api/v1/platform/me": { body: { ...STAFF, mfa_verified: false } } });
    render(<App />);
    expect(await screen.findByText(/two-factor authentication/)).toBeInTheDocument();
  });

  it("lists organisations and opens one as a member with a reason", async () => {
    window.history.pushState(null, "", "/platform");
    const open = vi.fn();
    vi.stubGlobal("open", open);
    const calls = mockApi(
      platform({
        "POST /api/v1/platform/tenants/o1/support-sessions": {
          body: { url: "https://brightminds.tutortrack.app/api/v1/support/enter?token=t" },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByText("£57.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Bright Minds" }));
    fireEvent.click(await screen.findByRole("button", { name: "View as" }));
    const form = screen.getByRole("form", { name: "View the account as owner@example.com" });
    fireEvent.change(within(form).getByLabelText("Reason"), {
      target: { value: "Ticket 123: invoices" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Open account" }));
    await vi.waitFor(() =>
      expect(open).toHaveBeenCalledWith(
        "https://brightminds.tutortrack.app/api/v1/support/enter?token=t",
        "_blank",
        "noopener",
      ),
    );
    expect(calls.find((c) => c.path.endsWith("/support-sessions"))?.body).toMatchObject({
      membership_id: "m1",
      reason: "Ticket 123: invoices",
      write: false,
    });
  });

  it("turns a flag on for everyone", async () => {
    window.history.pushState(null, "", "/platform/flags");
    const flag = {
      key: "new-calendar", description: "", enabled_globally: false, plan_keys: ["team"],
      rollout_percent: 10, overrides: [], updated_at: "2026-10-01T00:00:00Z",
    }; // prettier-ignore
    const calls = mockApi(
      platform({
        "GET /api/v1/platform/flags": { body: [flag] },
        "PATCH /api/v1/platform/flags/new-calendar": { body: { ...flag, enabled_globally: true } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByLabelText("On for everyone"));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ enabled_globally: true }),
    );
  });

  it("replays a dead-lettered event", async () => {
    window.history.pushState(null, "", "/platform/operations");
    const calls = mockApi(
      platform({
        "GET /api/v1/platform/operations": {
          body: {
            outbox_pending: 2, outbox_lag_seconds: 4, dead_letters: 1, queues: { celery: 0 },
            payment_webhooks_unprocessed: 0, payment_webhooks_failed: 0,
            billing_webhooks_unprocessed: 0, billing_webhooks_failed: 0,
            dead_letters_by_type: [],
          },
        }, // prettier-ignore
        "GET /api/v1/platform/dead-letters": {
          body: {
            results: [
              {
                id: "e1", event_type: "lesson.completed", organisation_name: "Bright Minds",
                occurred_at: "2026-10-09T10:00:00Z", dead_lettered_at: "2026-10-09T10:05:00Z",
                attempts: 8, last_error: "boom",
              },
            ],
            next: null,
            previous: null,
          },
        }, // prettier-ignore
        "GET /api/v1/platform/notices": { body: [] },
        "POST /api/v1/platform/dead-letters/replay": { body: { count: 1 } },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Dead letters", { selector: "dt" })).toBeInTheDocument();
    fireEvent.click(await screen.findByLabelText("Select lesson.completed"));
    fireEvent.click(screen.getByRole("button", { name: "Replay 1 event" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/replay"))?.body).toEqual({ ids: ["e1"] }),
    );
  });
});

describe("support access and status", () => {
  it("shows the organisation when support visited and posted notices", async () => {
    window.history.pushState(null, "", "/settings");
    mockApi({
      "GET /api/v1/me": {
        body: {
          ...ME,
          membership: { ...ME.membership, role: "owner" },
          permissions: {
            ...ME.permissions,
            "support.access.view": "all",
            "support.access.manage": "all",
          },
        },
      },
      "GET /api/v1/organisation": { body: { status: "active" } },
      "GET /api/v1/me/organisations": { body: [] },
      "GET /api/v1/status": {
        body: {
          notices: [
            {
              id: "n1", message: "Card payments are delayed", severity: "warning",
              starts_at: "2026-10-10T08:00:00Z", ends_at: null,
            },
          ],
          status_page_url: "",
        },
      }, // prettier-ignore
      "GET /api/v1/support-access": {
        body: {
          requires_grant: false,
          grants: [],
          sessions: [
            {
              id: "s1", staff_name: "Pat Support", viewed_as: "owner@example.com",
              reason: "Ticket 123", ticket: "123", write: false,
              created_at: "2026-10-09T10:00:00Z", entered_at: null, ended_at: null,
            },
          ],
        },
      }, // prettier-ignore
    });
    render(<App />);
    expect(await screen.findByText(/Pat Support viewed the account/)).toBeInTheDocument();
    expect(screen.getByText("Card payments are delayed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Grant access" })).toBeInTheDocument();
  });
});
