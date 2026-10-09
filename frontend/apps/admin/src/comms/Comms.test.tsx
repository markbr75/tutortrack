import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

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
};

const REMINDER = {
  key: "lesson_reminder",
  label: "Lesson reminder",
  category: "scheduling",
  audience: "client",
  channels: ["email", "sms"],
  available_channels: ["email", "sms", "in_app"],
  enabled: true,
  timing: [1440, 120],
  has_timing: true,
  transactional: false,
  customised: false,
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

describe("communications", () => {
  it("turns off reminder texts and keeps 24h and 2h emails", async () => {
    window.history.pushState(null, "", "/settings/notifications");
    const calls = mockApi(
      base({
        "GET /api/v1/notification-settings": { body: [REMINDER] },
        "PUT /api/v1/notification-settings/lesson_reminder": (body) => ({
          body: { ...REMINDER, ...(body as object) },
        }),
      }),
    );
    render(<App />);
    const form = await screen.findByRole("form", { name: "Lesson reminder" });
    expect(within(form).getByLabelText(/Hours before/)).toHaveValue("24, 2");
    fireEvent.click(within(form).getByLabelText("Text"));
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        enabled: true,
        channels: ["email"],
        timing: [1440, 120],
      }),
    );
  });

  it("previews and saves a template", async () => {
    window.history.pushState(null, "", "/settings/notifications");
    const calls = mockApi(
      base({
        "GET /api/v1/notification-settings": { body: [REMINDER] },
        "GET /api/v1/message-templates/lesson_reminder/email": {
          body: {
            type_key: "lesson_reminder",
            channel: "email",
            subject: "Reminder",
            body: "Hello {{ recipient.first_name }}",
            customised: false,
            version: 0,
            variables: ["recipient.first_name", "lesson.title"],
          },
        },
        "POST /api/v1/message-templates/lesson_reminder/email/preview": {
          body: { subject: "Reminder", body: "Hi Priya", segments: 1 },
        },
        "PUT /api/v1/message-templates/lesson_reminder/email": (body) => ({
          body: {
            type_key: "lesson_reminder",
            channel: "email",
            ...(body as object),
            customised: true,
            version: 1,
            variables: [],
          },
        }),
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit wording" }));
    const editor = await screen.findByRole("region", { name: "Wording: Lesson reminder" });
    const bodyField = await within(editor).findByLabelText("Message");
    fireEvent.change(bodyField, { target: { value: "Hi {{ recipient.first_name }}" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Preview" }));
    expect(await within(editor).findByText("Hi Priya")).toBeInTheDocument();
    fireEvent.click(within(editor).getByRole("button", { name: "Save wording" }));
    expect(await within(editor).findByText("Your version 1")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      subject: "Reminder",
      body: "Hi {{ recipient.first_name }}",
    });
  });

  it("shows unread notifications and marks them read", async () => {
    const calls = mockApi(
      base({
        "GET /api/v1/notifications/unread-count": { body: { unread: 2 } },
        "GET /api/v1/notifications": {
          body: {
            results: [
              {
                id: "n1",
                type_key: "staff_dispute",
                title: "A card payment was disputed",
                body: "Respond in Stripe",
                link: "/billing",
                read_at: null,
                created_at: "2026-10-09T10:00:00Z",
              },
            ],
            next: null,
          },
        },
        "POST /api/v1/notifications/read": { body: { unread: 0 } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Notifications (2 new)" }));
    expect(
      await screen.findByRole("link", { name: "A card payment was disputed" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mark all read" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/notifications/read")).toBe(true),
    );
  });
});
