import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";
import { enqueue, listOutbox, resetMemoryStorage } from "./outbox";

type Routes = Parameters<typeof mockApi>[0];

const started = new Date(Date.now() - 2 * 3600_000).toISOString();
const ended = new Date(Date.now() - 3600_000).toISOString();

const lesson = {
  id: "l1",
  title: "GCSE Maths – Arjun",
  start: started,
  end: ended,
  status: "planned",
  online: false,
  meeting_url: "",
  notes_for_tutor: "",
  attendees: [{ id: "a1", name: "Arjun Patel", outcome: "" }],
};

const pack = {
  generated_at: started,
  days: 7,
  lessons: [
    {
      id: "l1",
      title: "GCSE Maths – Arjun",
      start: started,
      end: ended,
      status: "planned",
      attendees: [{ id: "a1", name: "Arjun Patel", outcome: "" }],
      report: null,
      report_fields: [
        { key: "covered", label: "What we covered", type: "rich_text", required: true },
      ],
    },
  ],
};

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": {
      body: { membership: { role: "tutor" }, user: { id: "u1", email: "nia@example.com" } },
    },
    "GET /api/v1/tutor/me": {
      body: {
        id: "t1",
        name: "Nia Adeyemi",
        email: "nia@example.com",
        can_cancel: false,
        can_edit_lessons: false,
        can_see_pay: false,
      },
    },
    "GET /api/v1/lessons/l1": { body: lesson },
    "GET /api/v1/tutor/offline": { body: pack },
    ...extra,
  };
}

function goOffline(offline: boolean) {
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(!offline);
  window.dispatchEvent(new Event(offline ? "offline" : "online"));
}

beforeEach(() => resetMemoryStorage());

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

describe("tutor offline", () => {
  it("completes a lesson and writes the report without a signal, then syncs", async () => {
    goOffline(true);
    window.history.pushState(null, "", "/portal/tutor/lessons/l1");
    const calls = mockApi(
      routes({
        "POST /api/v1/lessons/l1/complete": { body: { id: "l1", status: "completed" } },
        "POST /api/v1/lessons/l1/reports": { status: 201, body: { id: "r1" } },
        "POST /api/v1/lesson-reports/r1/submit": { body: { id: "r1", status: "submitted" } },
      }),
    );
    render(<App />);
    const register = await screen.findByRole("form", { name: "Register" });
    fireEvent.click(within(register).getByRole("button", { name: "Complete and write report" }));

    // The report form comes from the offline pack; nothing was sent.
    const covered = await screen.findByLabelText("What we covered *");
    expect(screen.getByText(/You're offline\./)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    fireEvent.change(covered, { target: { value: "Fractions" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit report" }));
    expect(await screen.findByText(/Ready to submit/)).toBeInTheDocument();
    expect(await screen.findByText("2 changes are waiting to sync.")).toBeInTheDocument();

    goOffline(false);
    await waitFor(async () => expect(await listOutbox()).toEqual([]));
    const posts = calls.filter((c) => c.method === "POST").map((c) => c.path);
    expect(posts).toEqual([
      "/api/v1/lessons/l1/complete",
      "/api/v1/lessons/l1/reports",
      "/api/v1/lesson-reports/r1/submit",
    ]);
    expect(calls.find((c) => c.path.endsWith("/submit"))?.body).toEqual({
      answers: { covered: "Fractions" },
    });
    await waitFor(() => expect(screen.queryByText(/waiting to sync/)).not.toBeInTheDocument());
  });

  it("shows changes that need review, with the reason and what to do", async () => {
    await enqueue(
      {
        kind: "lesson.complete",
        label: "GCSE Maths – Arjun",
        lessonId: "l1",
        reportId: null,
        body: { attendance: [], actual_start: null, actual_end: null, override_balance: false },
        etag: null,
        csrf: null,
      },
      "k1",
    );
    window.history.pushState(null, "", "/portal/tutor/lessons/l1");
    mockApi(
      routes({
        "POST /api/v1/lessons/l1/complete": {
          status: 422,
          body: { type: "x/rule", title: "Rule", status: 422, detail: "Already completed." },
        },
      }),
    );
    render(<App />);
    const review = await screen.findByRole("region", { name: "Your changes need review" });
    expect(within(review).getByText(/Already completed\./)).toBeInTheDocument();
    expect(within(review).getByRole("link", { name: /Open the lesson/ })).toHaveAttribute(
      "href",
      "/portal/tutor/lessons/l1",
    );
    fireEvent.click(within(review).getByRole("button", { name: /Discard/ }));
    await waitFor(() => expect(screen.queryByRole("region")).not.toBeInTheDocument());
  });

  it("tells families they're offline", async () => {
    goOffline(true);
    mockApi({
      "GET /api/v1/me": { body: { membership: null, user: { id: "u2" } } },
    });
    render(<App />);
    expect(await screen.findByText(/Reconnect to see the latest/)).toBeInTheDocument();
  });
});
