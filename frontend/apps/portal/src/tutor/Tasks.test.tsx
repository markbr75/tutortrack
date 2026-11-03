import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const BASE = {
  "GET /api/v1/me": { body: { membership: { role: "tutor" }, user: { email: "n@x.com" } } },
  "GET /api/v1/tutor/me": {
    body: { id: "t1", name: "Nia", email: "n@x.com", can_cancel: true, can_edit_lessons: false,
            can_see_pay: true },
  }, // prettier-ignore
};
const task = (fields: Record<string, unknown>) => ({
  id: "s1", run: "r1", pathway: "Join a job", stage: "before", name: "Read the handover",
  step_type: "acknowledge", status: "open", due_at: null, reason: "", result: {},
  view: { title: "Handover", text: "Arrive early.", link: "" }, ...fields,
}); // prettier-ignore

describe("tutor tasks (E34-T02)", () => {
  it("reads and acknowledges a step", async () => {
    window.history.pushState(null, "", "/portal/tutor/tasks");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/me/tasks": { body: [task({})] },
      "POST /api/v1/me/tasks/s1/complete": { body: task({ status: "done" }) },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Join a job" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Read: Read the handover" }));
    expect(screen.getByText("Arrive early.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "I've read this" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/s1/complete"))).toBe(true));
  });

  it("books a call from the free times and shows the booked call", async () => {
    window.history.pushState(null, "", "/portal/tutor/tasks");
    const booked = task({
      id: "s2", name: "Book a call", step_type: "book_call", status: "done",
      result: { start: "2026-11-05T10:00:00Z", meeting_url: "https://meet.example/abc" },
    }); // prettier-ignore
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/me/tasks": {
        body: [
          task({ name: "Intro call", step_type: "book_call",
                 view: { title: "Intro", minutes: 20, host: "Sam", slots: ["2026-11-05T10:00:00Z"] } }),
          booked,
        ],
      }, // prettier-ignore
      "POST /api/v1/me/tasks/s1/complete": { body: booked },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Choose a time: Intro call" }));
    expect(screen.getByText("A 20-minute call with Sam.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Book" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/s1/complete"))?.body).toEqual({
        start: "2026-11-05T10:00:00Z",
      }),
    );
    expect(screen.getByRole("link", { name: "Join the call: Book a call" })).toHaveAttribute(
      "href",
      "https://meet.example/abc",
    );
  });

  it("says when a step waits for review or was sent back", async () => {
    window.history.pushState(null, "", "/portal/tutor/tasks");
    mockApi({
      ...BASE,
      "GET /api/v1/me/tasks": {
        body: [
          task({ status: "review" }),
          task({ id: "s3", name: "About you", step_type: "questions", reason: "Add more detail",
                 view: { fields: [{ key: "why", label: "Why?", type: "text", required: true }] } }),
        ],
      }, // prettier-ignore
    });
    render(<App />);
    expect(await screen.findByText("Waiting for review")).toBeInTheDocument();
    expect(screen.getByText("Sent back: Add more detail")).toBeInTheDocument();
  });
});
