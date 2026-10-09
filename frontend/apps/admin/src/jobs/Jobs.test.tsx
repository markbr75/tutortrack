import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const PERMS = {
  ...ME.permissions,
  "jobs.job.view": "all",
  "jobs.job.create": "all",
  "jobs.job.edit": "all",
  "jobs.job.manage_tutors": "all",
  "jobs.job.change_status": "all",
  "billing.rates.view_charge": "all",
  "billing.rates.view_pay": "all",
  "people.student.view": "all",
  "people.student.edit": "all",
};

const JOB = {
  id: "j1",
  reference: "JOB-000001",
  name: "GCSE Maths – Arjun Patel",
  client: "c1",
  client_name: "The Patel Family",
  service_name: "GCSE Maths 1:1",
  status: "active",
  currency: "GBP",
  charge_rate: { amount: "42.0000", currency: "GBP" },
  billing_method: "pay_as_you_go",
  default_schedule: [{ weekday: 1, time: "16:30" }],
  students: [{ id: "js1", student: "s1", student_name: "Arjun Patel", charge_rate_override: null }],
  tutors: [
    {
      id: "jt1",
      tutor: "t1",
      tutor_name: "Nia Adeyemi",
      role: "lead",
      status: "active",
      pay_rate_override: null,
    },
  ],
};

const SUMMARY = {
  per_lesson: {
    charge: { amount: "42.00", currency: "GBP" },
    pay: { amount: "25.00", currency: "GBP" },
    margin: { amount: "17.00", currency: "GBP" },
    margin_percent: "40.5",
  },
  trace: ["job rate £42.00/h", "60 minutes"],
  lessons_planned: 0,
  lessons_completed: 0,
  hours_delivered: "0",
  delivered: null,
  next_lesson_at: null,
  last_lesson_at: null,
};

function base(permissions: Record<string, string> = PERMS) {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions } },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/notes": { body: { results: [], next: null } },
    "GET /api/v1/tutors": {
      body: {
        results: [
          { id: "t2", full_name: "Sam Clarke" },
          { id: "t1", full_name: "Nia Adeyemi" },
        ],
        next: null,
      },
    },
  };
}

describe("jobs", () => {
  it("shows a job with economics and the schedule", async () => {
    window.history.pushState(null, "", "/jobs/j1");
    mockApi({
      ...base(),
      "GET /api/v1/jobs/j1": { body: JOB },
      "GET /api/v1/jobs/j1/summary": { body: SUMMARY },
    });
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "GCSE Maths – Arjun Patel" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Tuesday 16:30")).toBeInTheDocument();
    expect(await screen.findByText("£17.00 (40.5%)")).toBeInTheDocument();
    expect(screen.getByText("job rate £42.00/h · 60 minutes")).toBeInTheDocument();
  });

  it("hides economics without rate permissions", async () => {
    window.history.pushState(null, "", "/jobs/j1");
    const calls = mockApi({
      ...base({ ...ME.permissions, "jobs.job.view": "own" }),
      "GET /api/v1/jobs/j1": { body: { ...JOB, charge_rate: undefined } },
    });
    render(<App />);
    await screen.findByRole("heading", { name: "GCSE Maths – Arjun Patel" });
    expect(screen.queryByText("Economics")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Change status")).not.toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/summary"))).toBe(false);
  });

  it("previews and confirms a tutor replacement", async () => {
    window.history.pushState(null, "", "/jobs/j1");
    const calls = mockApi({
      ...base(),
      "GET /api/v1/jobs/j1": { body: JOB },
      "GET /api/v1/jobs/j1/summary": { body: SUMMARY },
      "POST /api/v1/jobs/j1/tutors/jt1/replace": (body) => ({
        body: (body as { dry_run: boolean }).dry_run
          ? {
              lessons: [{ id: "l1", starts_at: "2026-11-03T16:30:00Z", conflict: "" }],
              conflicts: 0,
              new_assignment: null,
            }
          : { lessons: [], conflicts: 0, new_assignment: { id: "jt2" } },
      }),
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Replace Nia Adeyemi" }));
    const select = await screen.findByLabelText("Replace Nia Adeyemi with");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(2));
    fireEvent.change(select, { target: { value: "t2" } });
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-11-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(
      await screen.findByText("1 future lesson will move to the new tutor."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Replace tutor" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.path.endsWith("/replace")).map((c) => c.body)).toEqual([
        { tutor: "t2", effective_date: "2026-11-01", dry_run: true },
        { tutor: "t2", effective_date: "2026-11-01", dry_run: false },
      ]),
    );
  });

  it("moves a job on the board", async () => {
    window.history.pushState(null, "", "/jobs");
    const calls = mockApi({
      ...base(),
      "GET /api/v1/jobs": {
        body: { results: [{ ...JOB, status: "seeking_tutor", tutors: [] }], next: null },
      },
      "POST /api/v1/jobs/j1/status": { body: { ...JOB, status: "cancelled" } },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Board" }));
    const column = await screen.findByRole("region", { name: /Seeking tutor/ });
    fireEvent.change(within(column).getByLabelText("Move GCSE Maths – Arjun Patel"), {
      target: { value: "cancelled" },
    });
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        status: "cancelled",
        reason: "",
        future_lessons: "keep",
      }),
    );
  });

  it("sets up lessons from a student page", async () => {
    window.history.pushState(null, "", "/students/s1");
    const calls = mockApi({
      ...base(),
      "GET /api/v1/students/s1": {
        body: { id: "s1", client: "c1", full_name: "Arjun Patel", status: "active", subjects: [] },
      },
      "GET /api/v1/jobs": { body: { results: [], next: null } },
      "GET /api/v1/catalogue/services": {
        body: { results: [{ id: "sv1", name: "GCSE Maths 1:1" }], next: null },
      },
      "POST /api/v1/jobs/quick-setup": { status: 201, body: JOB },
      "GET /api/v1/jobs/j1": { body: JOB },
      "GET /api/v1/jobs/j1/summary": { body: SUMMARY },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Set up lessons" }));
    const form = await screen.findByRole("form", { name: "Set up lessons" });
    const service = within(form).getByLabelText(/Service/);
    await waitFor(() => expect(within(service).getAllByRole("option")).toHaveLength(2));
    fireEvent.change(service, { target: { value: "sv1" } });
    fireEvent.change(within(form).getByLabelText("Tutor"), { target: { value: "t1" } });
    fireEvent.change(within(form).getByLabelText("Day"), { target: { value: "1" } });
    fireEvent.change(within(form).getByLabelText("Time"), { target: { value: "16:30" } });
    fireEvent.click(within(form).getByRole("button", { name: "Create job" }));
    expect(
      await screen.findByRole("heading", { name: "GCSE Maths – Arjun Patel" }),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/jobs/quick-setup")?.body).toEqual({
      student: "s1",
      service: "sv1",
      tutor: "t1",
      charge_rate: null,
      schedule: [{ weekday: 1, time: "16:30" }],
    });
  });
});
