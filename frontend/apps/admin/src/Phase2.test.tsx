import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "./App";
import { ME, mockApi } from "./test-utils";

/* E03/E06/E08 Phase 2 admin pages: catalogue pricing tabs, requests, online booking
 * settings, custom roles, single sign-on and passkeys. */

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const gbp = (amount: string) => ({ amount, currency: "GBP" });

function base(permissions: Record<string, string>, extra: Record<string, unknown> = {}) {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: { ...ME.permissions, ...permissions } } },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    ...extra,
  } as Parameters<typeof mockApi>[0];
}

const SERVICE = { id: "sv1", name: "Maths 1:1", currency: "GBP", active: true };

describe("catalogue pricing (E06 Phase 2)", () => {
  it("edits the pay tier grid", async () => {
    window.history.pushState(null, "", "/catalogue");
    const calls = mockApi(
      base(
        { "catalogue.view": "all", "rates.manage": "all", "billing.rates.view_pay": "all" },
        {
          "GET /api/v1/catalogue/services": { body: { results: [SERVICE], next: null } },
          "GET /api/v1/catalogue/tax-rates": { body: [] },
          "GET /api/v1/catalogue/tier-rates": {
            body: {
              tiers: [{ id: "t1", name: "Senior", description: "", order: 1, archived_at: null }],
              cells: [{ service: "sv1", tier: "t1", pay_rate: gbp("30.0000"), charge_rate: null }],
            },
          },
          "POST /api/v1/catalogue/tier-rates": {
            body: { tiers: [], cells: [] },
          },
        },
      ),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Pay tiers" }));
    const input = await screen.findByLabelText("Pay for Maths 1:1 (Senior)");
    expect(input).toHaveValue("30");
    fireEvent.change(input, { target: { value: "32.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save rates" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        cells: [{ service: "sv1", tier: "t1", pay_rate: gbp("32.5") }],
      }),
    );
  });

  it("creates a room with resources", async () => {
    window.history.pushState(null, "", "/catalogue");
    const calls = mockApi(
      base(
        { "catalogue.view": "all", "catalogue.manage": "all" },
        {
          "GET /api/v1/catalogue/services": { body: { results: [], next: null } },
          "GET /api/v1/catalogue/rooms": {
            body: {
              results: [
                {
                  id: "r1",
                  name: "Room 1",
                  location_name: "Centre",
                  capacity: 4,
                  resources: [{ name: "Piano", quantity: 1 }],
                },
              ],
              next: null,
            },
          },
          "GET /api/v1/catalogue/locations": {
            body: { results: [{ id: "loc1", name: "Centre", type: "centre" }], next: null },
          },
          "POST /api/v1/catalogue/rooms": { status: 201, body: { id: "r2" } },
        },
      ),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Rooms" }));
    expect(await screen.findByText("Piano")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Location"), { target: { value: "loc1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Room 2" } });
    fireEvent.change(screen.getByLabelText("Resources"), {
      target: { value: "Whiteboard, Laptops" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create room" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        location: "loc1",
        name: "Room 2",
        resources_input: [
          { name: "Whiteboard", quantity: 1 },
          { name: "Laptops", quantity: 1 },
        ],
      }),
    );
  });
});

describe("requests (E08-T13..T15)", () => {
  it("approves a reschedule request at the chosen time and time off", async () => {
    window.history.pushState(null, "", "/requests");
    const calls = mockApi(
      base(
        {
          "scheduling.lesson.view": "all",
          "scheduling.lesson.edit": "all",
          "scheduling.availability.manage_others": "all",
        },
        {
          "GET /api/v1/reschedule-requests": {
            body: {
              results: [
                {
                  id: "rr1",
                  lesson: "l1",
                  lesson_title: "Maths with Arjun",
                  requester: "client",
                  proposed: [
                    { start: "2026-11-05T16:00:00Z", end: "2026-11-05T17:00:00Z" },
                    { start: "2026-11-06T16:00:00Z", end: "2026-11-06T17:00:00Z" },
                  ],
                  reason: "School trip",
                  status: "pending",
                  deadline: "2026-11-03T16:00:00Z",
                  original_start: "2026-11-04T16:00:00Z",
                  original_end: "2026-11-04T17:00:00Z",
                },
              ],
              next: null,
            },
          },
          "POST /api/v1/reschedule-requests/rr1/decide": { body: { id: "rr1" } },
          "GET /api/v1/time-off": {
            body: {
              results: [
                {
                  id: "to1",
                  tutor_name: "Nia Adeyemi",
                  start: "2026-11-10T00:00:00Z",
                  end: "2026-11-11T00:00:00Z",
                  reason: "Wedding",
                  status: "requested",
                },
              ],
              next: null,
            },
          },
          "POST /api/v1/time-off/to1/decide": { body: { id: "to1", status: "approved" } },
        },
      ),
    );
    render(<App />);
    const item = (await screen.findByText("Maths with Arjun")).closest("li")!;
    const moves = within(item).getAllByRole("button", { name: /Move to/ });
    expect(moves).toHaveLength(2);
    fireEvent.click(moves[1]!);
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("rr1/decide"))?.body).toMatchObject({
        approve: true,
        choice: 1,
      }),
    );
    const timeOff = (await screen.findByText("Nia Adeyemi")).closest("li")!;
    fireEvent.change(within(timeOff).getByLabelText("Note"), { target: { value: "Enjoy" } });
    fireEvent.click(within(timeOff).getByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("to1/decide"))?.body).toEqual({
        approve: true,
        note: "Enjoy",
      }),
    );
  });
});

describe("online booking settings (E08-T14)", () => {
  it("turns booking on with payment at booking", async () => {
    window.history.pushState(null, "", "/settings/booking");
    const settings = {
      enabled: false,
      allow_new_clients: true,
      min_notice_hours: 24,
      max_advance_days: 60,
      slot_interval_minutes: 30,
      buffer_minutes: 0,
      approval_required: false,
      payment: "none",
      hold_minutes: 10,
      cancellation_window_hours: 24,
      tutors: [],
      location: null,
      terms: "",
    };
    const calls = mockApi(
      base(
        { "scheduling.booking.settings": "all" },
        {
          "GET /api/v1/booking/settings": { body: settings },
          "PUT /api/v1/booking/settings": (body: unknown) => ({ body }),
        },
      ),
    );
    render(<App />);
    fireEvent.click(await screen.findByLabelText("Turn on online booking"));
    fireEvent.change(screen.getByLabelText("Payment"), { target: { value: "at_booking" } });
    fireEvent.change(screen.getByLabelText("Start times every (minutes)"), {
      target: { value: "60" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
        enabled: true,
        payment: "at_booking",
        slot_interval_minutes: 60,
      }),
    );
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });
});

describe("custom roles (E03-T11)", () => {
  it("clones a role, edits the matrix and assigns a member", async () => {
    window.history.pushState(null, "", "/team/roles");
    const role = {
      id: "cr1",
      name: "Scheduler",
      description: "",
      base_role: "coordinator",
      grants: { "scheduling.lesson.edit": "all" },
      members: 0,
      archived_at: null,
    };
    const calls = mockApi(
      base(
        { "team.view": "all", "team.roles.manage": "all" },
        {
          "GET /api/v1/custom-roles": { body: [role] },
          "POST /api/v1/custom-roles": {
            status: 201,
            body: { ...role, id: "cr2", name: "Finance lite" },
          },
          "GET /api/v1/permissions": {
            body: [
              {
                codename: "scheduling.lesson.edit",
                category: "scheduling",
                description: "Edit lessons",
              },
            ],
          },
          "GET /api/v1/memberships": {
            body: {
              results: [
                {
                  id: "m2",
                  role: "coordinator",
                  custom_roles: [],
                  user: { email: "jo@example.com" },
                },
              ],
              next: null,
            },
          },
          "PATCH /api/v1/custom-roles/cr1": { body: role },
          "PATCH /api/v1/memberships/m2": { body: {} },
        },
      ),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /^Scheduler/ }));
    const scope = await screen.findByLabelText("Who Edit lessons applies to");
    expect(scope).toHaveValue("all");
    fireEvent.change(scope, { target: { value: "own" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("custom-roles/cr1"))?.body).toEqual({
        grants: { "scheduling.lesson.edit": "own" },
      }),
    );
    fireEvent.click(await screen.findByLabelText(/jo@example.com/));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("memberships/m2"))?.body).toEqual({
        custom_roles: ["cr1"],
      }),
    );
    fireEvent.change(screen.getByLabelText("Role name"), { target: { value: "Finance lite" } });
    fireEvent.change(screen.getByLabelText("Start from"), { target: { value: "finance" } });
    fireEvent.click(screen.getByRole("button", { name: "Create role" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        name: "Finance lite",
        clone_from: "finance",
      }),
    );
  });
});

describe("single sign-on (E03-T12)", () => {
  it("saves a SAML set-up and shows what to give the identity provider", async () => {
    window.history.pushState(null, "", "/settings/sso");
    const sso = {
      protocol: "oidc",
      enabled: false,
      name: "Company sign-in",
      email_domains: [],
      enforce: false,
      auto_provision: false,
      default_role: "tutor",
      issuer: "",
      client_id: "",
      has_client_secret: false,
      idp_entity_id: "",
      idp_sso_url: "",
      idp_certificate: "",
      sp_entity_id: "https://bm.tutortrack.app/api/v1/auth/org-sso/metadata",
      acs_url: "https://bm.tutortrack.app/api/v1/auth/org-sso/acs",
      callback_url: "https://bm.tutortrack.app/api/v1/auth/org-sso/callback",
      complete: false,
    };
    const calls = mockApi(
      base(
        { "security.sso.manage": "all" },
        {
          "GET /api/v1/security/sso": { body: sso },
          "PUT /api/v1/security/sso": { body: { ...sso, protocol: "saml" } },
        },
      ),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Protocol"), { target: { value: "saml" } });
    expect(screen.getByText(sso.acs_url)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Email domains"), {
      target: { value: "school.org, academy.org" },
    });
    fireEvent.change(screen.getByLabelText("Identity provider entity ID"), {
      target: { value: "https://idp" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
        protocol: "saml",
        email_domains: ["school.org", "academy.org"],
        idp_entity_id: "https://idp",
      }),
    );
  });
});

describe("passkeys (E03-T08)", () => {
  it("lists and removes passkeys on the account page", async () => {
    window.history.pushState(null, "", "/account");
    const calls = mockApi(
      base(
        {},
        {
          "GET /api/v1/me/passkeys": {
            body: [
              {
                id: "pk1",
                name: "Laptop",
                backed_up: true,
                transports: [],
                created_at: "2026-10-01T10:00:00Z",
                last_used_at: null,
              },
            ],
          },
          "DELETE /api/v1/me/passkeys/pk1": { status: 204, body: null },
          "GET /api/v1/me/sessions": { body: [] },
          "GET /api/v1/me/logins": { body: [] },
        },
      ),
    );
    render(<App />);
    expect(await screen.findByText("Laptop")).toBeInTheDocument();
    expect(screen.getByText("Not used yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove Laptop" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });
});
