import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "./App";
import { mockApi } from "./test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const FAMILY_ME = {
  role: "client",
  organisation: { name: "Bright Minds", primary_colour: "" },
  clients: [{ id: "c1", name: "The Patels" }],
  students: [{ id: "s1", name: "Arjun Patel" }],
  features: {
    cancellations: false, absence: false, invoices: false, reports: false, profile: false,
    booking: false, reschedule: false, classes: false, learning: false,
  },
  welcome_text: "", help_url: "", terms_url: "",
}; // prettier-ignore

describe("your data (family portal)", () => {
  it("asks for a copy of a child's data", async () => {
    window.history.pushState(null, "", "/portal/privacy");
    const calls = mockApi({
      "GET /api/v1/me": { body: { membership: { role: "client" }, user: { email: "p@x.com" } } },
      "GET /api/v1/portal/me": { body: FAMILY_ME },
      "GET /api/v1/me/data-requests": { body: [] },
      "GET /api/v1/portal/profile": {
        body: {
          students: [{ id: "s1", first_name: "Arjun", last_name: "Patel", preferred_name: "" }],
        },
      },
      "POST /api/v1/me/data-requests": {
        status: 201,
        body: { id: "d1", reference: "DSAR-00003", kind: "access", status: "received",
                due_at: "2026-11-13T10:00:00Z" }, // prettier-ignore
      },
    } satisfies Routes);
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Your data" })).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("About"), { target: { value: "s1" } });
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByText(/Request DSAR-00003 received/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      kind: "access",
      details: "",
      student_id: "s1",
    });
  });
});

describe("tutor safeguarding tools", () => {
  const started = new Date(Date.now() - 3600_000).toISOString();
  const ends = new Date(Date.now() + 1800_000).toISOString();

  it("checks in and out of a home visit and raises a concern", async () => {
    window.history.pushState(null, "", "/portal/tutor/lessons/l1");
    let visits: unknown[] = [];
    const calls = mockApi({
      "GET /api/v1/me": { body: { membership: { role: "tutor" }, user: { email: "n@x.com" } } },
      "GET /api/v1/tutor/me": {
        body: { id: "t1", name: "Nia", email: "n@x.com", can_cancel: true,
                can_edit_lessons: false, can_see_pay: true }, // prettier-ignore
      },
      "GET /api/v1/lessons/l1": {
        body: {
          id: "l1", title: "GCSE Maths", start: started, end: ends, status: "planned",
          online: false, meeting_url: "", notes_for_tutor: "",
          attendees: [{ id: "a1", student: "s1", name: "Arjun Patel", outcome: "" }],
        }, // prettier-ignore
      },
      "GET /api/v1/lone-working/visits": () => ({
        body: { results: visits, next: null, previous: null },
      }),
      "POST /api/v1/lone-working/visits/check-in": () => {
        visits = [{ id: "v1", checked_in_at: started, checked_out_at: null, status: "checked_in" }];
        return { status: 201, body: visits[0] };
      },
      "POST /api/v1/safeguarding/concerns": {
        status: 201,
        body: { id: "g1", reference: "SG-00004", category: "neglect", status: "open" },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "I've arrived" }));
    expect(await screen.findByRole("button", { name: "I've left" })).toBeInTheDocument();
    expect(calls.find((c) => c.path.endsWith("/check-in"))?.body).toEqual({ lesson: "l1" });

    fireEvent.click(screen.getByRole("button", { name: "Raise a safeguarding concern" }));
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "neglect" } });
    fireEvent.change(screen.getByLabelText("What happened"), {
      target: { value: "Said he had no breakfast" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send to the safeguarding lead" }));
    expect(await screen.findByText(/SG-00004 has been passed/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/safeguarding/concerns")?.body).toMatchObject({
      category: "neglect",
      lesson: "l1",
      student: "s1",
      immediate_risk: false,
    });
  });
});
