import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const PERMS = {
  ...ME.permissions,
  "comms.settings.manage": "all",
  "comms.template.manage": "all",
  "comms.channels.manage": "all",
};

function base(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/notifications/unread-count": { body: { unread: 0 } },
    ...extra,
  };
}

/** A minimal EventSource the test drives. */
class FakeEventSource {
  static CLOSED = 2;
  static last: FakeEventSource | null = null;
  readyState = 1;
  url: string;
  onerror: (() => void) | null = null;
  listeners: Record<string, (() => void)[]> = {};
  constructor(url: string) {
    this.url = url;
    FakeEventSource.last = this;
  }
  addEventListener(kind: string, listener: () => void) {
    (this.listeners[kind] ??= []).push(listener);
  }
  emit(kind: string) {
    for (const listener of this.listeners[kind] ?? []) listener();
  }
  close() {
    this.readyState = 2;
  }
}

const RESET = {
  key: "account_password_reset",
  label: "Password reset",
  category: "account",
  audience: "user",
  channels: ["email"],
  available_channels: ["email"],
  enabled: true,
  timing: [],
  has_timing: false,
  transactional: true,
  locked: true,
  customised: false,
};

describe("communications (G4)", () => {
  it("updates the bell live over the event stream", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    let unread = 0;
    mockApi(
      base({
        "GET /api/v1/notifications/unread-count": () => ({ body: { unread } }),
        "GET /api/v1/dashboard": { body: {} },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("button", { name: "Notifications" })).toBeInTheDocument();
    expect(FakeEventSource.last?.url).toBe("/api/v1/notifications/stream");
    unread = 2;
    act(() => {
      FakeEventSource.last?.emit("ready");
      FakeEventSource.last?.emit("notification");
    });
    expect(
      await screen.findByRole("button", { name: "Notifications (2 new)" }),
    ).toBeInTheDocument();
  });

  it("keeps account emails switched on and edits a French version", async () => {
    window.history.pushState(null, "", "/settings/notifications");
    const calls = mockApi(
      base({
        "GET /api/v1/notification-settings": { body: [RESET] },
        "GET /api/v1/branches": { body: { results: [], next: null } },
        "GET /api/v1/message-templates/account_password_reset/email/variants": { body: [] },
        "GET /api/v1/message-templates/account_password_reset/email": (_body, url) => ({
          body: {
            type_key: "account_password_reset",
            channel: "email",
            subject: url.searchParams.get("locale") === "fr" ? "" : "Reset your password",
            body: "Hi {{ recipient.first_name }}: {{ link }}",
            customised: false,
            version: 0,
            variables: ["link"],
            locale: url.searchParams.get("locale") ?? "",
            branch: null,
          },
        }),
        "PUT /api/v1/message-templates/account_password_reset/email": (body) => ({
          body: { ...(body as object), customised: true, version: 1, variables: ["link"] },
        }),
      }),
    );
    render(<App />);
    const form = await screen.findByRole("form", { name: "Password reset" });
    expect(within(form).getByRole("checkbox", { name: "Password reset" })).toBeDisabled();
    expect(within(form).getByText(/can be edited but not switched off/)).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Edit wording" }));
    const language = await screen.findByLabelText(/Language/);
    fireEvent.change(language, { target: { value: "fr" } });
    fireEvent.blur(language);
    await waitFor(() => expect(screen.getByLabelText("Subject")).toHaveValue(""));
    fireEvent.change(screen.getByLabelText("Subject"), {
      target: { value: "Réinitialiser" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save wording" }));
    await waitFor(() => {
      const put = calls.find((c) => c.method === "PUT");
      expect(put?.search).toBe("?locale=fr");
    });
  });

  it("shows where Mailchimp sends unsubscribes back", async () => {
    window.history.pushState(null, "", "/settings/messaging");
    mockApi(
      base({
        "GET /api/v1/marketing-sync": {
          body: [
            {
              provider: "mailchimp",
              name: "Mailchimp",
              connection: "c1",
              account_name: "Bright Minds",
              status: "ok",
              audience_id: "aud1",
              audience_name: "Families",
              last_sync_at: null,
              error: "",
              webhook_url: "https://app.tutortrack.app/api/v1/webhooks/marketing/mailchimp/tok",
            },
          ],
        },
        "GET /api/v1/marketing-sync/mailchimp/audiences": { body: [] },
        "GET /api/v1/sender-domains": { body: { results: [], next: null } },
        "GET /api/v1/phone-numbers": { body: { results: [], next: null } },
        "GET /api/v1/whatsapp-templates": { body: { results: [], next: null } },
        "GET /api/v1/canned-replies": { body: { results: [], next: null } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Mailchimp and Brevo" }));
    expect(await screen.findByLabelText("Mailchimp webhook address")).toHaveValue(
      "https://app.tutortrack.app/api/v1/webhooks/marketing/mailchimp/tok",
    );
  });
});
