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
    "comms.inbox.view": "all",
    "comms.inbox.reply": "all",
    "comms.inbox.assign": "all",
  },
};

const page = (results: unknown[]) => ({ body: { results, next: null, previous: null } });

const THREAD = {
  id: "th1",
  subject: "Thursday",
  kind: "client",
  client: "c1",
  tutor: null,
  party: "The Patels",
  contact_name: "",
  contact_email: "",
  contact_phone: "",
  status: "open",
  snoozed_until: null,
  assignee: null,
  assignee_name: "",
  channel: "email",
  last_message_at: "2026-10-14T08:00:00Z",
  last_message_preview: "Can Arjun start at 5pm?",
  awaiting_reply_since: "2026-10-13T08:00:00Z",
  sla_due_at: "2026-10-14T08:00:00Z",
  sla_breached: true,
  flagged: true,
  unread: 1,
  created_at: "2026-10-13T08:00:00Z",
};

const MESSAGES = [
  {
    id: "m1",
    thread: "th1",
    direction: "inbound",
    channel: "email",
    author_type: "contact",
    author_id: "ct1",
    author_name: "Priya Patel",
    subject: "Thursday",
    body: "Can Arjun start at 5pm? Call me on 07700 900123",
    attachments: [],
    flags: ["contact_details"],
    delivery_status: "",
    created_at: "2026-10-14T08:00:00Z",
  },
  {
    id: "m2",
    thread: "th1",
    direction: "internal",
    channel: "note",
    author_type: "user",
    author_id: "u1",
    author_name: "Sam",
    subject: "",
    body: "Check Nia's diary",
    attachments: [],
    flags: [],
    delivery_status: "",
    created_at: "2026-10-14T08:10:00Z",
  },
];

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: STAFF },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/threads": page([THREAD]),
    "GET /api/v1/threads/counts": {
      body: { open: 1, mine: 0, unassigned: 1, snoozed: 0, flagged: 1 },
    },
    "GET /api/v1/threads/th1": {
      body: { ...THREAD, participants: [], reply_address: "reply+bm.abc.def@reply.example" },
    },
    "GET /api/v1/threads/th1/messages": { body: MESSAGES },
    "GET /api/v1/threads/assignees": { body: [{ id: "u1", name: "Sam Lee" }] },
    "GET /api/v1/canned-replies": page([
      { id: "cr1", title: "Thanks", body: "Thanks, we'll call you.", shortcut: "" },
    ]),
    ...extra,
  };
}

describe("inbox (E13-T11)", () => {
  it("reads a conversation, replies, adds a note and assigns", async () => {
    window.history.pushState(null, "", "/inbox");
    const calls = mockApi(
      routes({
        "POST /api/v1/threads/th1/messages": { status: 201, body: MESSAGES[0] },
        "POST /api/v1/threads/th1/notes": { status: 201, body: MESSAGES[1] },
        "POST /api/v1/threads/th1/assign": { body: { ...THREAD, assignee: "u1" } },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("button", { name: "Unassigned (1)" })).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Conversations" });
    expect(within(list).getByText(/Reply overdue/)).toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button", { name: /The Patels/ }));
    expect(await screen.findByText("Check Nia's diary")).toBeInTheDocument();
    expect(screen.getByText("Flagged for review: contact details")).toBeInTheDocument();
    expect(
      screen.getByText("Email replies go to reply+bm.abc.def@reply.example"),
    ).toBeInTheDocument();
    const reply = screen.getByRole("form", { name: "Reply" });
    await within(reply).findByRole("option", { name: "Thanks" });
    fireEvent.change(within(reply).getByLabelText("Canned reply"), { target: { value: "cr1" } });
    expect(within(reply).getByLabelText("Message")).toHaveValue("Thanks, we'll call you.");
    fireEvent.click(within(reply).getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === "/api/v1/threads/th1/messages" && c.method === "POST")?.body,
      ).toEqual({
        body: "Thanks, we'll call you.",
        channel: "email",
        subject: "",
      }),
    );
    fireEvent.change(within(reply).getByLabelText("Message"), { target: { value: "VIP" } });
    fireEvent.click(within(reply).getByRole("button", { name: "Add internal note" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/notes"))?.body).toEqual({ body: "VIP" }),
    );
    fireEvent.change(await screen.findByLabelText("Assigned to"), { target: { value: "u1" } });
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/assign"))?.body).toEqual({ assignee: "u1" }),
    );
  });

  it("is hidden without permission", async () => {
    window.history.pushState(null, "", "/");
    mockApi(routes({ "GET /api/v1/me": { body: ME } }));
    render(<App />);
    await screen.findByRole("navigation", { name: /main/i }).catch(() => null);
    expect(screen.queryByRole("link", { name: "Inbox" })).not.toBeInTheDocument();
  });
});
