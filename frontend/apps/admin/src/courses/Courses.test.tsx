import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const COORDINATOR = {
  ...ME,
  membership: { ...ME.membership, role: "coordinator" },
  permissions: {
    ...ME.permissions,
    "courses.view": "all",
    "courses.manage": "all",
    "courses.enrolment.manage": "all",
    "courses.register.mark": "all",
    "courses.rollover.manage": "all",
  },
};

const CLASS = {
  id: "c1", branch: "b1", course: "co1", course_name: "Year 6 11+ Prep", term: "t1",
  term_name: "Autumn", name: "Saturday 10am", rrule: "FREQ=WEEKLY;BYDAY=SA", weekdays: [5],
  start_date: "2026-10-17", end_date: "2026-12-12", start_time: "10:00:00",
  duration_minutes: 60, timezone: "Europe/London", location: null, location_name: "",
  room: null, room_name: "Room 2", online: false, capacity: 8, min_size: 0, status: "open",
  waitlist_enabled: true, min_age: null, max_age: null, year_groups: [],
  teacher_pay_mode: "service", teacher_pay: {}, is_public: true, next_class: null,
  teachers: [], enrolled: 1, places_left: 7, waiting: 0, cancelled_at: null,
  cancel_reason: "", created_at: "2026-10-01T10:00:00Z",
}; // prettier-ignore

const ROSTER = [
  { enrolment: "e1", student: "s1", student_name: "Arjun Patel", client: "cl1",
    client_name: "The Patels", status: "enrolled", start_date: "2026-10-17", end_date: null,
    joined_via: "staff" },
]; // prettier-ignore

const QUOTE = {
  list_price: { amount: "120.00", currency: "GBP" }, price: { amount: "120.00", currency: "GBP" },
  discounts: [], pricing_model: "per_term", start_date: "2026-10-24",
  fee_due: { amount: "105.00", currency: "GBP" }, units: { basis: "sessions", total: 8, remaining: 7 },
  instalments: 1, registration_fee: { amount: "0.00", currency: "GBP" },
  materials_fee: { amount: "0.00", currency: "GBP" }, due_now: { amount: "105.00", currency: "GBP" },
  deposit: null, problems: [],
}; // prettier-ignore

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: COORDINATOR },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    ...extra,
  };
}

describe("courses and classes", () => {
  it("lists classes with places and status", async () => {
    window.history.pushState(null, "", "/courses");
    mockApi(
      routes({
        "GET /api/v1/terms": { body: { results: [], next: null, previous: null } },
        "GET /api/v1/classes": { body: { results: [CLASS], next: null, previous: null } },
        "GET /api/v1/courses": { body: { results: [], next: null, previous: null } },
        "GET /api/v1/tutors": { body: { results: [], next: null, previous: null } },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("link", { name: "Saturday 10am" })).toBeInTheDocument();
    expect(screen.getByText("1 of 8 taken")).toBeInTheDocument();
    expect(screen.getByText("Open for enrolment")).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "New class" })).toBeInTheDocument();
  });

  it("creates a course sized to a small group service", async () => {
    window.history.pushState(null, "", "/courses");
    const service = { id: "sv1", name: "11+ group class", format: "class", currency: "GBP",
      max_students: 8 }; // prettier-ignore
    const calls = mockApi(
      routes({
        "GET /api/v1/terms": { body: { results: [], next: null, previous: null } },
        "GET /api/v1/classes": { body: { results: [], next: null, previous: null } },
        "GET /api/v1/courses": { body: { results: [], next: null, previous: null } },
        "GET /api/v1/tutors": { body: { results: [], next: null, previous: null } },
        "GET /api/v1/catalogue/services": {
          body: { results: [service], next: null, previous: null },
        },
        "POST /api/v1/courses": { status: 201, body: { id: "co2" } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Courses" }));
    await screen.findByRole("option", { name: "11+ group class" });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "11+ Prep" } });
    fireEvent.change(screen.getByLabelText(/Scheduled as/), { target: { value: "sv1" } });
    const size = screen.getByLabelText("Usual class size");
    expect(size).toHaveValue(8);
    expect(screen.getByText(/allows up to 8/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Price/), { target: { value: "120" } });
    fireEvent.click(screen.getByRole("button", { name: "Create course" }));
    await vi.waitFor(() =>
      expect(
        calls.find((c) => c.method === "POST" && c.path === "/api/v1/courses")?.body,
      ).toMatchObject({ service: "sv1", default_capacity: 8 }),
    );
  });

  it("shows a class, prices a late joiner and enrols them", async () => {
    window.history.pushState(null, "", "/classes/c1");
    const calls = mockApi(
      routes({
        "GET /api/v1/classes/c1": { body: CLASS },
        "GET /api/v1/classes/c1/roster": { body: ROSTER },
        "GET /api/v1/classes/c1/sessions": { body: [] },
        "GET /api/v1/classes/c1/waitlist": { body: [] },
        "GET /api/v1/students": {
          body: {
            results: [{ id: "s2", full_name: "Maya Patel" }],
            next: null,
            previous: null,
          },
        },
        "POST /api/v1/enrolments/quote": { body: QUOTE },
        "POST /api/v1/enrolments": { status: 201, body: { id: "e2", status: "enrolled" } },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Saturday 10am" })).toBeInTheDocument();
    expect(screen.getByText("Arjun Patel")).toBeInTheDocument();
    expect(screen.getByText("7 places left", { exact: false })).toBeInTheDocument();
    await screen.findByRole("option", { name: "Maya Patel" });
    fireEvent.change(screen.getByLabelText("Student"), { target: { value: "s2" } });
    expect(await screen.findByText(/Joining late: 7 of 8/)).toBeInTheDocument();
    expect(screen.getByText("Due at enrolment: £105.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Enrol" }));
    await vi.waitFor(() =>
      expect(
        calls.find((c) => c.method === "POST" && c.path === "/api/v1/enrolments")?.body,
      ).toEqual({
        group_class: "c1",
        student: "s2",
        trial: false,
        override_capacity: false,
        skip_eligibility: false,
      }),
    );
  });

  it("takes the register with absence reasons", async () => {
    window.history.pushState(null, "", "/class-sessions/x1/register");
    const register = {
      session: "x1",
      lesson_status: "planned",
      rows: [
        { student: "s1", student_name: "Arjun", outcome: "present", late_minutes: null,
          absence_reason: "", makeup: false },
        { student: "s2", student_name: "Maya", outcome: "present", late_minutes: null,
          absence_reason: "", makeup: true },
      ],
    }; // prettier-ignore
    const calls = mockApi(
      routes({
        "GET /api/v1/class-sessions/x1/register": { body: register },
        "GET /api/v1/class-sessions/x1": {
          body: {
            id: "x1",
            course_name: "11+",
            class_name: "Saturday",
            start: "2026-10-17T09:00:00Z",
          },
        },
        "POST /api/v1/class-sessions/x1/register": {
          body: { ...register, lesson_status: "completed" },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Makeup")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Attendance for Maya"), {
      target: { value: "absent_notified" },
    });
    fireEvent.change(screen.getByLabelText("Reason Maya was away"), { target: { value: "Ill" } });
    fireEvent.click(screen.getByRole("button", { name: "Save register" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        rows: [
          { student: "s1", outcome: "present", absence_reason: "" },
          { student: "s2", outcome: "absent_notified", absence_reason: "Ill" },
        ],
      }),
    );
    expect(await screen.findByText("Register saved.")).toBeInTheDocument();
  });

  it("lets a family keep next term's place from the email link", async () => {
    window.history.pushState(null, "", "/re-enrol/tok");
    const page = {
      student: "Arjun", course_name: "Year 6 11+ Prep", class_name: "Saturday 10am",
      term: "Spring", starts: "2027-01-09", start_time: "10:00", status: "pending",
      deadline: "2026-12-01T12:00:00Z", mode: "confirm", open: true,
    }; // prettier-ignore
    const calls = mockApi({
      "GET /api/v1/public/re-enrol/tok": { body: page },
      "POST /api/v1/public/re-enrol/tok": { body: { ...page, status: "confirmed" } },
    });
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Arjun's place next term" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Keep the place" }));
    expect(await screen.findByText("Keeping the place")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ confirm: true });
  });
});
