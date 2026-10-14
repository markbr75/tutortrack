import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const STAFF = {
  ...ME,
  membership: { ...ME.membership, role: "coordinator" },
  permissions: {
    ...ME.permissions,
    "comms.broadcast.view": "all",
    "comms.broadcast.send": "all",
  },
};

const page = (results: unknown[]) => ({ body: { results, next: null, previous: null } });

const STATS = {
  recipients: 5,
  pending: 0,
  queued: 4,
  skipped: 1,
  sent: 4,
  delivered: 4,
  opened: 3,
  clicked: 1,
  bounced: 0,
  failed: 0,
  unsubscribed: 1,
};

const BROADCAST = {
  id: "b1",
  name: "Half term",
  channel: "email",
  purpose: "operational",
  subject: "Half term",
  body: "Hello {{ recipient.first_name }}",
  whatsapp_template: null,
  segment: null,
  segment_name: "",
  audience: "contacts",
  definition: { client_statuses: ["active"] },
  attachment_ids: [],
  status: "sent",
  scheduled_for: null,
  started_at: "2026-10-14T09:00:00Z",
  finished_at: "2026-10-14T09:05:00Z",
  cancelled_at: null,
  stats: STATS,
  created_at: "2026-10-13T09:00:00Z",
  updated_at: "2026-10-14T09:05:00Z",
};

const OPTIONS = {
  branches: [],
  tags: [{ value: "tg1", name: "VIP" }],
  saved_views: [],
  group_classes: [],
  pipeline_stages: [],
  client_statuses: [
    { value: "active", name: "Active" },
    { value: "dormant", name: "Dormant" },
  ],
  student_statuses: [],
  tutor_statuses: [{ value: "active", name: "Active" }],
};

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: STAFF },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/broadcasts": page([BROADCAST]),
    "GET /api/v1/broadcasts/b1": { body: BROADCAST },
    "POST /api/v1/broadcasts/b1/preview": {
      body: { subject: "Half term", body: "Hello Priya", segments: 0 },
    },
    "GET /api/v1/broadcasts/b1/recipients": page([
      {
        id: "r1",
        recipient_type: "contact",
        recipient_id: "c1",
        name: "Priya Patel",
        address: "priya@example.com",
        status: "queued",
        skip_reason: "",
        message: "m1",
        message_status: "opened",
        batch: 1,
      },
      {
        id: "r2",
        recipient_type: "contact",
        recipient_id: "c2",
        name: "Sam Smith",
        address: "",
        status: "skipped",
        skip_reason: "no_address",
        message: null,
        message_status: "",
        batch: 0,
      },
    ]),
    "GET /api/v1/segments/options": { body: OPTIONS },
    "GET /api/v1/segments": page([]),
    ...extra,
  };
}

describe("broadcasts (E13-T10)", () => {
  it("shows delivery statistics and recipients", async () => {
    window.history.pushState(null, "", "/broadcasts");
    mockApi(routes());
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Half term" }));
    const detail = await screen.findByRole("region", { name: /Half term · Sent/ });
    expect(within(detail).getByText("Hello Priya")).toBeInTheDocument();
    const opened = within(detail).getByText("Opened").closest("div")!;
    expect(within(opened).getByText("3")).toBeInTheDocument();
    expect(within(detail).getByText("opened")).toBeInTheDocument();
    expect(within(detail).getByText("1 has no address for this channel")).toBeInTheDocument();
  });

  it("checks the audience, saves a draft and sends it", async () => {
    window.history.pushState(null, "", "/broadcasts");
    const draft = { ...BROADCAST, id: "b2", name: "Offer", status: "draft", stats: STATS };
    const calls = mockApi(
      routes({
        "POST /api/v1/segments/preview": {
          body: {
            total: 6,
            sendable: 4,
            skipped: { no_consent: 2 },
            sample: [{ name: "Priya Patel", address: "priya@example.com", kind: "contact" }],
          },
        },
        "POST /api/v1/broadcasts": { status: 201, body: draft },
        "GET /api/v1/broadcasts/b2": { body: draft },
        "POST /api/v1/broadcasts/b2/preview": {
          body: { subject: "Summer school", body: "Book now", segments: 0 },
        },
        "POST /api/v1/broadcasts/b2/schedule": { body: { ...draft, status: "scheduled" } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "New broadcast" }));
    const form = screen.getByRole("form", { name: "New broadcast" });
    fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Offer" } });
    fireEvent.change(within(form).getByLabelText("Kind of message"), {
      target: { value: "marketing" },
    });
    fireEvent.click(await within(form).findByLabelText("VIP"));
    fireEvent.click(within(form).getByRole("button", { name: "Check who it reaches" }));
    expect(await within(form).findByText("Reaches 4 of 6 people.")).toBeInTheDocument();
    expect(within(form).getByText("2 haven't agreed to marketing")).toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText("Subject"), {
      target: { value: "Summer school" },
    });
    fireEvent.change(within(form).getByLabelText("Message"), { target: { value: "Book now" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === "/api/v1/broadcasts" && c.method === "POST")?.body,
      ).toMatchObject({
        name: "Offer",
        purpose: "marketing",
        channel: "email",
        definition: { client_statuses: ["active"], tags: ["tg1"], contacts: "primary" },
      }),
    );
    const detail = await screen.findByRole("region", { name: /Offer · Draft/ });
    fireEvent.click(within(detail).getByRole("button", { name: "Send now" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/schedule"))?.body).toEqual({
        scheduled_for: null,
      }),
    );
  });
});
