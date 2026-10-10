import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const ADMIN = {
  ...ME,
  permissions: {
    ...ME.permissions,
    "developer.apikey.manage": "all",
    "developer.webhook.view": "all",
    "developer.webhook.manage": "all",
    "developer.app.manage": "all",
    "developer.app.connect": "all",
    "developer.sandbox.manage": "all",
  },
};
const BASE = {
  "GET /api/v1/me": { body: ADMIN },
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};
const page = <T,>(results: T[]) => ({ next: null, previous: null, results });

const SCOPES = [
  { key: "clients:read", resource: "clients", access: "read",
    description: "Read: Clients and contacts", permissions: ["people.client.view"] },
  { key: "clients:write", resource: "clients", access: "write",
    description: "Read and write: Clients and contacts", permissions: ["people.client.create"] },
]; // prettier-ignore

const KEY = {
  id: "k1", name: "CRM sync", display: "ttk_abcdefabcdef…", prefix: "abcdefabcdef",
  scopes: ["clients:read"], branch: null, branch_name: "", ip_allowlist: [], expires_at: null,
  revoked_at: null, last_used_at: null, last_used_ip: null, rate_limit_per_minute: null,
  rotated_from: null, user: "u1", user_name: "Sam", active: true,
  created_at: "2026-10-10T09:00:00Z",
}; // prettier-ignore

const ENDPOINT = {
  id: "e1", url: "https://hooks.example.com/tt", description: "", events: ["lesson.completed"],
  branch: null, branch_name: "", status: "active", source: "manual", api_version: "2026-10-01",
  failing_since: null, disabled_at: null, secret_rotating: false,
  created_at: "2026-10-10T09:00:00Z",
}; // prettier-ignore

const DELIVERY = {
  id: "d1", endpoint: "e1", endpoint_url: ENDPOINT.url, event_id: "ev1",
  event_type: "lesson.completed", status: "retrying", attempt_count: 2, last_status_code: 500,
  last_attempt_at: "2026-10-10T09:01:00Z", delivered_at: null, is_test: false,
  redelivery_of: null, created_at: "2026-10-10T09:00:00Z",
}; // prettier-ignore

describe("developer settings", () => {
  it("creates an API key and shows the secret once", async () => {
    window.history.pushState(null, "", "/developer");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/developer/overview": {
        body: { api_keys: 0, connected_apps: 0, webhook_endpoints: 0, deliveries_24h: 0,
                failed_24h: 0, sandbox_of: "", rate_limit_per_minute: 600,
                burst_per_second: 100 },
      }, // prettier-ignore
      "GET /api/v1/developer/scopes": { body: SCOPES },
      "GET /api/v1/developer/api-keys": { body: page([KEY]) },
      "POST /api/v1/developer/api-keys": {
        status: 201,
        body: { ...KEY, id: "k2", name: "Zap", secret: "ttk_abcdefabcdef_" + "0".repeat(48) },
      },
    });
    render(<App />);
    expect(await screen.findByText("600", { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "API keys" }));
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Zap" } });
    fireEvent.click(await screen.findByLabelText(/Read: Clients and contacts/));
    fireEvent.click(screen.getByRole("button", { name: "Create key" }));
    expect(await screen.findByTestId("secret")).toHaveTextContent("ttk_abcdefabcdef_");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({ name: "Zap", scopes: ["clients:read"] });
    expect(screen.getByText("ttk_abcdefabcdef…")).toBeInTheDocument();
  });

  it("adds a webhook endpoint, sends a test and shows the delivery log", async () => {
    window.history.pushState(null, "", "/developer");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/developer/overview": {
        body: { api_keys: 0, connected_apps: 0, webhook_endpoints: 1, deliveries_24h: 1,
                failed_24h: 1, sandbox_of: "", rate_limit_per_minute: 600,
                burst_per_second: 100 },
      }, // prettier-ignore
      "GET /api/v1/webhook-event-types": {
        body: [{ key: "lesson.completed", aggregate: "lesson", subject_type: "lesson",
                 description: "", version: 1 }],
      }, // prettier-ignore
      "GET /api/v1/webhook-endpoints": { body: page([ENDPOINT]) },
      "POST /api/v1/webhook-endpoints": {
        status: 201,
        body: { ...ENDPOINT, id: "e2", secret: "whsec_new" },
      },
      "POST /api/v1/webhook-endpoints/e1/test": {
        status: 202,
        body: { ...DELIVERY, id: "d2", event_type: "webhook.test" },
      },
      "GET /api/v1/webhook-deliveries": { body: page([DELIVERY]) },
      "GET /api/v1/webhook-deliveries/d1": {
        body: {
          ...DELIVERY,
          attempts: [
            { number: 1, attempted_at: "2026-10-10T09:00:00Z", status_code: 500,
              succeeded: false, error: "HTTP 500", request_headers: {},
              response_snippet: "boom", duration_ms: 12 },
          ],
          body: { type: "lesson.completed" },
        },
      }, // prettier-ignore
      "POST /api/v1/webhook-deliveries/d1/retry-now": { status: 202, body: null },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Webhooks" }));
    fireEvent.change(await screen.findByLabelText("Endpoint URL"), {
      target: { value: "https://hooks.example.com/new" },
    });
    fireEvent.change(await screen.findByLabelText("Event"), { target: { value: "lesson.*" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("button", { name: "Add endpoint" }));
    expect(await screen.findByTestId("secret")).toHaveTextContent("whsec_new");
    expect(calls.find((c) => c.path === "/api/v1/webhook-endpoints" && c.method === "POST")?.body)
      .toMatchObject({ url: "https://hooks.example.com/new", events: ["lesson.*"] }); // prettier-ignore

    fireEvent.click(screen.getByRole("button", { name: "Send test event" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Test event sent");
    fireEvent.click(screen.getByRole("button", { name: "Delivery log" }));
    fireEvent.click(await screen.findByRole("button", { name: "lesson.completed" }));
    expect(await screen.findByText("boom")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry now" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/webhook-deliveries/d1/retry-now")).toBe(true),
    );
  });

  it("lists connected apps and disconnects one", async () => {
    window.history.pushState(null, "", "/developer");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/developer/overview": {
        body: { api_keys: 0, connected_apps: 1, webhook_endpoints: 0, deliveries_24h: 0,
                failed_24h: 0, sandbox_of: "", rate_limit_per_minute: 600,
                burst_per_second: 100 },
      }, // prettier-ignore
      "GET /api/v1/developer/scopes": { body: SCOPES },
      "GET /api/v1/developer/oauth-apps": { body: page([]) },
      "GET /api/v1/developer/connected-apps": {
        body: page([
          { id: "g1", user: "u1", user_email: "sam@example.com", scopes: ["clients:read"],
            last_used_at: null, created_at: "2026-10-10T09:00:00Z",
            application: { id: "a1", name: "Zapier", description: "", homepage_url: "",
                           logo_url: "", client_id: "ttapp_z", confidential: true,
                           redirect_uris: [], allowed_scopes: [], partner_key: "zapier",
                           created_at: "2026-10-10T09:00:00Z" } },
        ]),
      }, // prettier-ignore
      "POST /api/v1/developer/connected-apps/g1/revoke": { status: 204, body: null },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Apps" }));
    fireEvent.click(await screen.findByRole("button", { name: "Disconnect Zapier" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/developer/connected-apps/g1/revoke")).toBe(true),
    );
  });
});

describe("developer docs and marketplace", () => {
  it("shows guides, samples and the changelog", async () => {
    window.history.pushState(null, "", "/developer/docs");
    mockApi({
      ...BASE,
      "GET /api/v1/developer/changelog": {
        body: [{ released_on: "2026-10-10", title: "Public API", change_kind: "added",
                 description: "Keys, OAuth and webhooks" }],
      }, // prettier-ignore
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Webhooks" })).toBeInTheDocument();
    expect(screen.getByText(/Webhook-Signature: t=/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Python" }));
    expect(screen.getByText(/import requests/)).toBeInTheDocument();
    expect(await screen.findByText(/Keys, OAuth and webhooks/)).toBeInTheDocument();
  });

  it("lists integrations by category with their status", async () => {
    window.history.pushState(null, "", "/settings/marketplace");
    mockApi({
      ...BASE,
      "GET /api/v1/developer/marketplace": {
        body: [
          { key: "stripe", name: "Stripe", category: "payments", description: "Cards",
            status: "connected", settings_path: "/settings/payments", kind: "native",
            client_id: "", homepage_url: "" },
          { key: "xero", name: "Xero", category: "accounting", description: "Sync",
            status: "coming_soon", settings_path: "", kind: "native", client_id: "",
            homepage_url: "" },
          { key: "zapier", name: "Zapier", category: "automation", description: "Zaps",
            status: "available", settings_path: "/developer/apps", kind: "partner",
            client_id: "ttapp_z", homepage_url: "" },
        ],
      }, // prettier-ignore
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Payments" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage Stripe" })).toBeInTheDocument();
    expect(screen.getByText("Coming soon")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect Zapier" })).toBeInTheDocument();
  });

  it("asks for consent and redirects back with the decision", async () => {
    window.history.pushState(
      null,
      "",
      "/oauth/authorize?client_id=ttapp_z&redirect_uri=https%3A%2F%2Fz.example%2Fcb" +
        "&response_type=code&scope=clients%3Aread&state=s1",
    );
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/oauth/authorize": {
        body: {
          application: { id: "a1", name: "Zapier", description: "Automate", homepage_url: "",
                         logo_url: "", client_id: "ttapp_z", confidential: true,
                         redirect_uris: [], allowed_scopes: [], partner_key: "zapier",
                         created_at: "2026-10-10T09:00:00Z" },
          scopes: [{ key: "clients:read", description: "Read: Clients and contacts" }],
          redirect_uri: "https://z.example/cb", state: "s1", organisation_name: "Bright Minds",
        },
      }, // prettier-ignore
      "POST /api/v1/oauth/authorize": { body: { redirect_to: "https://z.example/cb?code=c" } },
    });
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Zapier wants to access Bright Minds" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Read: Clients and contacts")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Allow" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://z.example/cb?code=c"));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      client_id: "ttapp_z",
      approve: true,
    });
  });
});
