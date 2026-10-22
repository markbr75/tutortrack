import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const started = new Date(Date.now() - 2 * 3600_000).toISOString();
const ended = new Date(Date.now() - 3600_000).toISOString();

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": {
      body: { membership: { role: "tutor" }, user: { email: "nia@example.com" } },
    },
    "GET /api/v1/tutor/me": {
      body: {
        id: "t1",
        name: "Nia Adeyemi",
        email: "nia@example.com",
        can_cancel: true,
        can_edit_lessons: false,
        can_see_pay: true,
      },
    },
    ...extra,
  };
}

describe("tutor portal", () => {
  it("opens for an owner who teaches (a sole trader)", async () => {
    window.history.pushState(null, "", "/portal/");
    mockApi(
      routes({
        "GET /api/v1/me": {
          body: {
            membership: { role: "owner", teaches: true },
            user: { email: "sam@example.com", first_name: "Sam" },
          },
        },
        "GET /api/v1/tutor/today": {
          body: {
            date: "2026-10-10",
            lessons: [],
            reports_due: 0,
            offers: 0,
            unread: 0,
            earnings_this_month: { amount: "0.00", currency: "GBP" },
          },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Today" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Tutor menu" })).toBeInTheDocument();
  });

  it("shows today with counts and lessons", async () => {
    window.history.pushState(null, "", "/portal/");
    mockApi(
      routes({
        "GET /api/v1/tutor/today": {
          body: {
            date: "2026-10-10",
            lessons: [
              {
                id: "l1",
                title: "GCSE Maths – Arjun",
                start: started,
                end: ended,
                status: "planned",
                online: false,
                meeting_url: "",
                location: "Centre",
                students: ["Arjun Patel"],
              },
            ],
            reports_due: 2,
            offers: 1,
            unread: 0,
            earnings_this_month: { amount: "250.00", currency: "GBP" },
          },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Today" })).toBeInTheDocument();
    expect(screen.getByText("£250.00")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open and complete GCSE Maths/ })).toHaveAttribute(
      "href",
      "/portal/tutor/lessons/l1",
    );
  });

  it("counts lessons still to mark on earlier days in the Today pill", async () => {
    window.history.pushState(null, "", "/portal/");
    const today = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    mockApi(
      routes({
        "GET /api/v1/tutor/today": {
          body: {
            date: `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`,
            lessons: [
              {
                id: "l1",
                title: "GCSE Maths – Arjun",
                start: started,
                end: ended,
                status: "planned",
                online: false,
                meeting_url: "",
                location: "Centre",
                students: ["Arjun Patel"],
              },
            ],
            // Today's lesson plus two from earlier days.
            unmarked_lessons: 3,
            reports_due: 1,
            offers: 0,
            unread: 0,
            earnings_this_month: { amount: "0.00", currency: "GBP" },
          },
        },
      }),
    );
    render(<App />);
    const earlier = await screen.findByRole("link", { name: /Earlier lessons to mark/ });
    expect(earlier).toHaveTextContent("2");
    expect(earlier).toHaveAttribute("href", "/portal/tutor/schedule");
    expect(screen.getByRole("link", { name: /Reports to write/ })).toHaveTextContent("1");
    const nav = screen.getByRole("navigation", { name: "Tutor menu" });
    // The pill: three lessons to mark plus one report.
    expect(within(nav).getAllByRole("link", { description: "4 waiting" }).length).toBeGreaterThan(
      0,
    );
  });

  it("completes a lesson with the register, then writes and submits the report", async () => {
    window.history.pushState(null, "", "/portal/tutor/lessons/l1");
    const report = {
      id: "r1",
      lesson: "l1",
      lesson_title: "GCSE Maths – Arjun",
      status: "pending",
      returned_note: "",
      answers: {},
      template_fields: [
        {
          key: "covered",
          label: "What we covered",
          type: "rich_text",
          required: true,
          visibility: "student",
        },
      ],
    };
    const calls = mockApi(
      routes({
        "GET /api/v1/lessons/l1": {
          body: {
            id: "l1",
            title: "GCSE Maths – Arjun",
            start: started,
            end: ended,
            status: "planned",
            online: false,
            meeting_url: "",
            notes_for_tutor: "Bring past papers",
            attendees: [{ id: "a1", name: "Arjun Patel", outcome: "" }],
          },
        },
        "POST /api/v1/lessons/l1/complete": { body: { id: "l1", status: "completed" } },
        "POST /api/v1/lessons/l1/reports": { status: 201, body: report },
        "GET /api/v1/lesson-reports/r1": { body: report },
        "POST /api/v1/lesson-reports/r1/submit": { body: { ...report, status: "submitted" } },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Bring past papers")).toBeInTheDocument();
    const register = screen.getByRole("form", { name: "Register" });
    fireEvent.change(within(register).getByLabelText("Attendance for Arjun Patel"), {
      target: { value: "late" },
    });
    fireEvent.change(within(register).getByLabelText("Minutes late"), { target: { value: "5" } });
    fireEvent.click(within(register).getByRole("button", { name: "Complete and write report" }));
    const covered = await screen.findByLabelText("What we covered *");
    expect(calls.find((c) => c.path.endsWith("/complete"))?.body).toEqual({
      attendance: [{ attendee: "a1", outcome: "late", late_minutes: 5 }],
      actual_start: null,
      actual_end: null,
      override_balance: false,
    });
    fireEvent.change(covered, { target: { value: "Fractions" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit report" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/submit"))?.body).toEqual({
        answers: { covered: "Fractions" },
      }),
    );
  });
});
