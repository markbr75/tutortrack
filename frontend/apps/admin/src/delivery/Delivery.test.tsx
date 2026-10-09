import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { addDays, startOfWeek } from "../calendar/dates";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const PERMS = {
  ...ME.permissions,
  "scheduling.lesson.view": "all",
  "scheduling.lesson.complete": "all",
  "scheduling.lesson.cancel": "all",
  "delivery.report.view": "all",
  "delivery.report.write": "all",
  "delivery.report.approve": "all",
  "delivery.report.share": "all",
  "delivery.policy.manage": "all",
  "delivery.template.manage": "all",
};

type Routes = Parameters<typeof mockApi>[0];

function base(extra: Routes = {}, permissions = PERMS): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions } },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    ...extra,
  };
}

// Monday of this week, 09:00 local: in the past for most of the week, so "complete" shows.
const monday = startOfWeek(new Date());
const start = new Date(monday);
start.setHours(0, 5, 0, 0);
const end = new Date(start.getTime() + 60 * 60_000);
const ITEM = {
  kind: "lesson",
  id: "l1",
  title: "GCSE Maths – Arjun Patel",
  start: start.toISOString(),
  end: end.toISOString(),
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  status: "planned",
  colour: "#2563eb",
  service: "sv1",
  job: null,
  series: null,
  location: "",
  online: true,
  tutors: [{ id: "t1", name: "Nia Adeyemi" }],
  students: [
    { id: "s1", name: "Arjun Patel" },
    { id: "s2", name: "Maya Patel" },
  ],
  locked: false,
};
const LESSON = {
  ...ITEM,
  attendees: [
    { id: "a1", student: "s1", name: "Arjun Patel", client: "c1" },
    { id: "a2", student: "s2", name: "Maya Patel", client: "c1" },
  ],
  tutors: [{ id: "lt1", tutor: "t1", name: "Nia Adeyemi" }],
};

const FIELDS = [
  { key: "covered", label: "What we covered", type: "rich_text", required: true,
    visibility: "student" },
  { key: "effort", label: "Effort", type: "rating", required: false, visibility: "client" },
  { key: "private_notes", label: "Private notes", type: "text", required: false,
    visibility: "staff" },
]; // prettier-ignore

function report(extra: Record<string, unknown> = {}) {
  return {
    id: "r1",
    lesson: "l1",
    lesson_title: "GCSE Maths – Arjun Patel",
    lesson_start: start.toISOString(),
    lesson_end: end.toISOString(),
    lesson_status: "completed",
    tutor: "t1",
    tutor_name: "Nia Adeyemi",
    students: [{ id: "s1", name: "Arjun Patel" }],
    status: "draft",
    sla_state: "due",
    due_at: addDays(end, 1).toISOString(),
    submitted_at: null,
    approved_at: null,
    shared_at: null,
    overdue_at: null,
    escalated_at: null,
    pay_held: false,
    returned_note: "",
    template_name: "Simple",
    template_version_number: 1,
    template_fields: FIELDS,
    answers: {},
    updated_at: start.toISOString(),
    ...extra,
  };
}

describe("lesson delivery", () => {
  it("completes a lesson with the register", async () => {
    if (new Date() < end) return; // only meaningful once Monday's lesson is over
    window.history.pushState(null, "", "/calendar");
    const calls = mockApi(
      base({
        "GET /api/v1/calendar": { body: [ITEM] },
        "GET /api/v1/tutors": { body: { results: [], next: null } },
        "GET /api/v1/lessons/l1": { body: LESSON },
        "POST /api/v1/lessons/l1/complete": { body: { ...LESSON, status: "completed" } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /GCSE Maths – Arjun Patel/ }), {
      detail: 0,
    });
    const dialog = await screen.findByRole("dialog", { name: /GCSE Maths/, hidden: true });
    fireEvent.click(within(dialog).getByRole("button", { name: "Mark completed", hidden: true }));
    const maya = await within(dialog).findByLabelText("Attendance for Maya Patel");
    fireEvent.change(maya, { target: { value: "late" } });
    fireEvent.change(within(dialog).getByLabelText("Minutes late for Maya Patel"), {
      target: { value: "10" },
    });
    fireEvent.change(within(dialog).getByLabelText("Attendance for Arjun Patel"), {
      target: { value: "no_show" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Complete lesson", hidden: true }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/lessons/l1/complete")?.body).toEqual({
        attendance: [
          { attendee: "a1", outcome: "no_show", late_minutes: null },
          { attendee: "a2", outcome: "late", late_minutes: 10 },
        ],
        actual_start: null,
        actual_end: null,
        override_balance: false,
      }),
    );
  });

  it("autosaves a draft and submits the report", async () => {
    window.history.pushState(null, "", "/reports/r1");
    const calls = mockApi(
      base({
        "GET /api/v1/lesson-reports/r1": { body: report() },
        "GET /api/v1/lesson-reports/r1/comments": { body: [] },
        "PUT /api/v1/lesson-reports/r1": (body) => ({
          body: report({ answers: (body as { answers: object }).answers }),
        }),
        "POST /api/v1/lesson-reports/r1/submit": (body) => ({
          body: report({
            status: "submitted",
            sla_state: "shared",
            answers: (body as { answers: object }).answers,
          }),
        }),
      }),
    );
    render(<App />);
    const covered = await screen.findByLabelText(/What we covered/);
    expect(screen.getByText(/Student and client can see/)).toBeInTheDocument();
    fireEvent.change(covered, { target: { value: "Fractions" } });
    fireEvent.click(screen.getByRole("radio", { name: "4 out of 5" }));
    await waitFor(
      () =>
        expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({
          answers: { covered: "Fractions", effort: 4 },
        }),
      { timeout: 3000 },
    );
    fireEvent.click(screen.getByRole("button", { name: "Submit report" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/submit"))?.body).toEqual({
        answers: { covered: "Fractions", effort: 4 },
      }),
    );
    expect(await screen.findByText(/This report can no longer be edited/)).toBeInTheDocument();
  });

  it("approves a submitted report from the review queue", async () => {
    window.history.pushState(null, "", "/reports");
    const submitted = report({ status: "submitted", sla_state: "submitted" });
    const calls = mockApi(
      base({
        "GET /api/v1/lesson-reports": { body: { results: [submitted], next: null } },
        "GET /api/v1/lesson-reports/r1": { body: submitted },
        "GET /api/v1/lesson-reports/r1/comments": { body: [] },
        "POST /api/v1/lesson-reports/r1/approve": {
          body: report({ status: "approved", sla_state: "shared", shared_at: end.toISOString() }),
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "To approve" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/lesson-reports")).toBe(true));
    fireEvent.click(await screen.findByRole("link", { name: "GCSE Maths – Arjun Patel" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/Shared with the client/)).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/approve"))).toBe(true);
  });

  it("bulk-completes unconfirmed lessons", async () => {
    window.history.pushState(null, "", "/unconfirmed");
    const calls = mockApi(
      base({
        "GET /api/v1/unconfirmed-lessons": { body: [LESSON] },
        "POST /api/v1/lessons/bulk": { body: { succeeded: ["l1"], failed: {} } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByLabelText("Select GCSE Maths – Arjun Patel"));
    fireEvent.click(screen.getByRole("button", { name: "Mark completed" }));
    expect(await screen.findByText("1 updated, 0 couldn't be changed.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      action: "complete",
      ids: ["l1"],
      reason: "",
      cancelled_by: "admin",
    });
  });

  it("saves the cancellation policy and builds a report template", async () => {
    window.history.pushState(null, "", "/lesson-policies");
    const calls = mockApi(
      base({
        "GET /api/v1/cancellation-policies": { body: [] },
        "POST /api/v1/cancellation-policies": (body) => ({
          status: 201,
          body: { id: "p1", version: 1, ...(body as object) },
        }),
        "GET /api/v1/report-templates": { body: [] },
        "POST /api/v1/report-templates": (body) => ({
          status: 201,
          body: { id: "rt1", version: 1, ...(body as object) },
        }),
      }),
    );
    render(<App />);
    const window_ = await screen.findByLabelText(/Free cancellation with at least/);
    fireEvent.change(window_, { target: { value: "48" } });
    fireEvent.click(screen.getByRole("button", { name: "Save policy" }));
    await waitFor(() =>
      expect(
        (
          calls.find((c) => c.path === "/api/v1/cancellation-policies" && c.method === "POST")
            ?.body as { rules: { free_window_hours: number } }
        ).rules.free_window_hours,
      ).toBe(48),
    );

    fireEvent.click(screen.getByRole("tab", { name: "Report templates" }));
    fireEvent.click(await screen.findByRole("button", { name: "New template" }));
    fireEvent.change(screen.getByLabelText("Template name"), { target: { value: "Maths" } });
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Topics we did" } });
    fireEvent.click(screen.getByRole("button", { name: "Add a question" }));
    const labels = screen.getAllByLabelText("Question");
    fireEvent.change(labels[1]!, { target: { value: "Effort" } });
    fireEvent.change(screen.getAllByLabelText("Type")[1]!, { target: { value: "select" } });
    fireEvent.change(screen.getByLabelText("Options (one per line)"), {
      target: { value: "Low\nHigh" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save template" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === "/api/v1/report-templates" && c.method === "POST")?.body,
      ).toMatchObject({
        name: "Maths",
        fields: [
          { key: "topics_we_did", label: "Topics we did", type: "rich_text", required: true },
          { key: "effort", label: "Effort", type: "select", options: ["Low", "High"] },
        ],
      }),
    );
  });
});
