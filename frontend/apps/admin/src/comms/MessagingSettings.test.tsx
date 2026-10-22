import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const ADMIN = {
  ...ME,
  permissions: { ...ME.permissions, "comms.channels.manage": "all" },
};

const page = (results: unknown[]) => ({ body: { results, next: null, previous: null } });

const DOMAIN = {
  id: "d1",
  domain: "brightminds.co.uk",
  local_part: "hello",
  from_address: "hello@brightminds.co.uk",
  status: "pending",
  dns_records: [
    {
      purpose: "dkim",
      record_type: "TXT",
      host: "pm._domainkey.brightminds.co.uk",
      value: "k=rsa;p=ABC",
      verified: false,
    },
    {
      purpose: "spf",
      record_type: "TXT",
      host: "brightminds.co.uk",
      value: "v=spf1 include:spf.mtasv.net ~all",
      verified: false,
    },
  ],
  verified_at: null,
  last_checked_at: null,
  error: "",
  is_default: true,
  created_at: "2026-10-14T08:00:00Z",
};

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: ADMIN },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/sender-domains": page([DOMAIN]),
    ...extra,
  };
}

describe("messaging settings (E13-T12)", () => {
  it("shows DNS records and checks a domain", async () => {
    window.history.pushState(null, "", "/settings/messaging");
    const calls = mockApi(
      routes({
        "POST /api/v1/sender-domains/d1/check": { body: { ...DOMAIN, status: "verified" } },
        "POST /api/v1/sender-domains": { status: 201, body: { ...DOMAIN, id: "d2" } },
      }),
    );
    render(<App />);
    // The panel is titled by the address; its status is a word in the line beneath.
    expect(
      await screen.findByRole("heading", { name: "hello@brightminds.co.uk" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Waiting for DNS")).toBeInTheDocument();
    expect(screen.getByText("pm._domainkey.brightminds.co.uk")).toBeInTheDocument();
    expect(screen.getByText("Recommended")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check DNS" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/check"))).toBe(true));
    const form = screen.getByRole("form", { name: "Add domain" });
    fireEvent.change(within(form).getByLabelText("Domain"), {
      target: { value: "minds.example" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Add domain" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === "/api/v1/sender-domains" && c.method === "POST")?.body,
      ).toEqual({
        domain: "minds.example",
        local_part: "hello",
      }),
    );
  });

  it("connects Mailchimp, chooses an audience and syncs", async () => {
    window.history.pushState(null, "", "/settings/messaging");
    let connected = false;
    const row = (provider: string, name: string) => ({
      provider,
      name,
      connection: connected && provider === "mailchimp" ? "ic1" : null,
      account_name: connected && provider === "mailchimp" ? "Bright Minds" : "",
      status: connected ? "active" : "",
      audience_id: connected && provider === "mailchimp" ? "aud1" : "",
      audience_name: "",
      last_sync_at: null,
      error: "",
    });
    const calls = mockApi(
      routes({
        "GET /api/v1/marketing-sync": () => ({
          body: [row("mailchimp", "Mailchimp"), row("brevo", "Brevo")],
        }),
        "POST /api/v1/integrations/connections": () => {
          connected = true;
          return { status: 201, body: { id: "ic1" } };
        },
        "GET /api/v1/marketing-sync/mailchimp/audiences": {
          body: [{ id: "aud1", name: "Families", members: 2 }],
        },
        "POST /api/v1/marketing-sync/mailchimp/sync": {
          body: { upserted: 2, unsubscribed: 1, failed: 0 },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Mailchimp and Brevo" }));
    fireEvent.change(await screen.findByLabelText("Mailchimp API key"), {
      target: { value: "abc-us21" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Connect" })[0]!);
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/integrations/connections")?.body).toMatchObject({
        provider: "mailchimp",
        level: "organisation",
        api_key: "abc-us21",
      }),
    );
    expect(await screen.findByText("Families (2 members)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    expect(
      await screen.findByText("Synced: 2 added or updated, 1 unsubscribed."),
    ).toBeInTheDocument();
  });
});
