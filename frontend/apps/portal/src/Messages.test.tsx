import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "./App";
import { mockApi } from "./test-utils";

/* E15-T09: messages with the business (and tutors) through the E13 inbox, and booking a
 * makeup lesson with a makeup credit. */

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const ME = {
  role: "client",
  organisation: { name: "Bright Minds", primary_colour: "" },
  clients: [{ id: "c1", name: "The Patels" }],
  students: [{ id: "s1", name: "Arjun Patel" }],
  features: {
    cancellations: false,
    absence: false,
    invoices: false,
    reports: false,
    profile: false,
    booking: true,
    reschedule: false,
    messages: true,
    message_tutors: true,
    makeups: true,
  },
  welcome_text: "",
  help_url: "",
  terms_url: "",
};

const THREAD = {
  id: "th1",
  subject: "Thursday",
  kind: "client",
  with_name: "",
  last_message_at: "2026-10-14T09:00:00Z",
  last_message_preview: "Yes, see you at 5!",
  unread: 1,
  closed: false,
};

const DETAIL = {
  ...THREAD,
  unread: 0,
  messages: [
    {
      id: "m1",
      author_name: "Priya Patel",
      from_business: false,
      mine: true,
      channel: "chat",
      body: "Can Arjun start at 5pm?",
      attachments: [],
      created_at: "2026-10-14T08:00:00Z",
    },
    {
      id: "m2",
      author_name: "Sam (Bright Minds)",
      from_business: true,
      mine: false,
      channel: "chat",
      body: "Yes, see you at 5!",
      attachments: [
        { id: "f1", filename: "map.pdf", content_type: "application/pdf", size_bytes: 3 },
      ],
      created_at: "2026-10-14T09:00:00Z",
    },
  ],
};

describe("portal messages", () => {
  it("lists conversations, reads one and replies", async () => {
    window.history.pushState(null, "", "/portal/messages");
    const calls = mockApi({
      "GET /api/v1/portal/me": { body: ME },
      "GET /api/v1/portal/threads": { body: [THREAD] },
      "GET /api/v1/portal/threads/th1": { body: DETAIL },
      "POST /api/v1/portal/threads/th1/messages": {
        status: 201,
        body: { ...DETAIL.messages[0], id: "m3", body: "Thanks!" },
      },
    });
    render(<App />);
    expect(await screen.findByRole("link", { name: "Messages" })).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Conversations" });
    expect(within(list).getByText("1 new")).toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button", { name: /Thursday/ }));
    expect(await screen.findByText("Can Arjun start at 5pm?")).toBeInTheDocument();
    expect(screen.getByText("Attachment: map.pdf")).toBeInTheDocument();
    expect(screen.getByText(/^You ·/)).toBeInTheDocument();
    const reply = screen.getByRole("form", { name: "Reply" });
    fireEvent.change(within(reply).getByLabelText("Your message"), {
      target: { value: "Thanks!" },
    });
    fireEvent.click(within(reply).getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        body: "Thanks!",
        attachments: [],
      }),
    );
  });

  it("starts a conversation with a tutor", async () => {
    window.history.pushState(null, "", "/portal/messages");
    const calls = mockApi({
      "GET /api/v1/portal/me": { body: ME },
      "GET /api/v1/portal/threads": { body: [] },
      "GET /api/v1/portal/messaging/tutors": { body: [{ id: "t1", name: "Nia Adeyemi" }] },
      "POST /api/v1/portal/threads": {
        status: 201,
        body: { ...DETAIL, id: "th2", kind: "tutor_family", with_name: "Nia Adeyemi" },
      },
      "GET /api/v1/portal/threads/th2": {
        body: { ...DETAIL, id: "th2", kind: "tutor_family", with_name: "Nia Adeyemi" },
      },
    });
    render(<App />);
    expect(await screen.findByText("No messages yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New message" }));
    const form = screen.getByRole("form", { name: "New message" });
    fireEvent.change(await within(form).findByLabelText("To"), { target: { value: "t1" } });
    fireEvent.change(within(form).getByLabelText("Subject"), { target: { value: "Homework" } });
    fireEvent.change(within(form).getByLabelText("Your message"), {
      target: { value: "Is chapter 3 due?" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        subject: "Homework",
        body: "Is chapter 3 due?",
        attachments: [],
        tutor: "t1",
      }),
    );
    expect(await screen.findByRole("heading", { name: /Nia Adeyemi/ })).toBeInTheDocument();
  });

  it("books a makeup lesson with a credit", async () => {
    const soon = new Date(Date.now() + 3 * 86_400_000).toISOString();
    window.history.pushState(null, "", "/portal/book");
    const calls = mockApi({
      "GET /api/v1/portal/me": { body: ME },
      "GET /api/v1/portal/booking/services": {
        body: [
          {
            id: "sv1",
            name: "Maths 1:1",
            description: "",
            duration_minutes: 60,
            delivery_mode: "in_person",
            price: { amount: "40.00", currency: "GBP" },
            tutors: [{ id: "t1", name: "Nia A." }],
          },
        ],
      },
      "GET /api/v1/portal/booking/slots": {
        body: [{ tutor: "t1", tutor_name: "Nia A.", start: soon, end: soon }],
      },
      "GET /api/v1/portal/makeup-credits": {
        body: [
          {
            id: "mc1",
            student: "s1",
            student_name: "Arjun Patel",
            source_lesson: "Maths with Nia",
            source_start: "2026-10-01T16:00:00Z",
            expires_at: "2026-11-01T16:00:00Z",
          },
        ],
      },
      "POST /api/v1/portal/booking/holds": { status: 400, body: { title: "stop here" } },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Lesson"), { target: { value: "sv1" } });
    fireEvent.change(await screen.findByLabelText("Use a makeup credit"), {
      target: { value: "mc1" },
    });
    fireEvent.click(await screen.findByRole("button", { name: /Nia A\./ }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        service: "sv1",
        makeup_credit: "mc1",
      }),
    );
  });

  it("hides messages when the organisation turns them off", async () => {
    window.history.pushState(null, "", "/portal/messages");
    mockApi({
      "GET /api/v1/portal/me": {
        body: { ...ME, features: { ...ME.features, messages: false } },
      },
    });
    render(<App />);
    expect(await screen.findByText("Messaging isn't available.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Messages" })).not.toBeInTheDocument();
  });
});
