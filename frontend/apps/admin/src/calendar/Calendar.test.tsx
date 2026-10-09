import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";
import { addDays, startOfWeek, toDateInput } from "./dates";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const PERMS = {
  ...ME.permissions,
  "scheduling.lesson.view": "all",
  "scheduling.lesson.create": "all",
  "scheduling.lesson.edit": "all",
  "scheduling.lesson.cancel": "all",
  "scheduling.lesson.complete": "all",
  "scheduling.override_conflicts": "all",
  "scheduling.availability.view": "all",
  "scheduling.availability.edit": "all",
  "scheduling.availability.manage_others": "all",
};

// A lesson on Tuesday of the current week at 16:00 local time.
const tuesday = addDays(startOfWeek(new Date()), 1);
const start = new Date(tuesday);
start.setHours(16, 0, 0, 0);
const end = new Date(start.getTime() + 60 * 60_000);

const LESSON = {
  kind: "lesson",
  id: "l1",
  title: "GCSE Maths – Arjun Patel",
  start: start.toISOString(),
  end: end.toISOString(),
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  status: "planned",
  colour: "#2563eb",
  service: "sv1",
  job: "j1",
  series: null,
  location: "",
  online: true,
  tutors: [{ id: "t1", name: "Nia Adeyemi" }],
  students: [{ id: "s1", name: "Arjun Patel" }],
  locked: false,
};

function base(extra: Record<string, unknown> = {}) {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/calendar": { body: [LESSON] },
    "GET /api/v1/tutors": {
      body: {
        results: [{ id: "t1", full_name: "Nia Adeyemi", email: "nia@example.com" }],
        next: null,
      },
    },
    "GET /api/v1/students": {
      body: { results: [{ id: "s1", full_name: "Arjun Patel" }], next: null },
    },
    "GET /api/v1/catalogue/services": {
      body: { results: [{ id: "sv1", name: "GCSE Maths 1:1" }], next: null },
    },
    ...extra,
  };
}

describe("calendar", () => {
  it("shows the week and cancels a lesson with the policy preview", async () => {
    window.history.pushState(null, "", "/calendar");
    const outcome = {
      kind: "late",
      charge_percent: "100.00",
      pay_percent: "50.00",
      policy_charge_percent: "100.00",
      policy_pay_percent: "50.00",
      notice_minutes: 600,
      makeup_credit: false,
      policy_name: "Default policy",
      message: "This is a late cancellation: client charged 100%, tutor paid 50%.",
    };
    const calls = mockApi({
      ...base(),
      "POST /api/v1/lessons/l1/cancel": (_body, url) => ({
        body: {
          outcome,
          lesson: url.searchParams.get("preview") ? null : { ...LESSON, status: "cancelled" },
          following_cancelled: 0,
        },
      }),
    });
    render(<App />);
    const item = await screen.findByRole("button", { name: /GCSE Maths – Arjun Patel/ });
    fireEvent.click(item, { detail: 0 });
    const dialog = await screen.findByRole("dialog", { name: /GCSE Maths/, hidden: true });
    expect(within(dialog).getByText("Nia Adeyemi")).toBeInTheDocument();
    expect(within(dialog).getByText("Online")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel lesson", hidden: true }));
    expect(await within(dialog).findByText(outcome.message)).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Ill" } });
    fireEvent.click(
      within(dialog).getAllByRole("button", { name: "Cancel lesson", hidden: true })[0]!,
    );
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/lessons/l1/cancel" && !c.search)?.body).toEqual({
        cancelled_by: "client",
        reason: "Ill",
        notify: true,
        scope: "this",
        override: null,
      }),
    );
    expect(calls.find((c) => c.search === "?preview=true")).toBeDefined();
    const range = calls.find((c) => c.path === "/api/v1/calendar");
    expect(range).toBeDefined();
  });

  it("reschedules with the keyboard form and can override a clash", async () => {
    window.history.pushState(null, "", "/calendar");
    let attempts = 0;
    const calls = mockApi({
      ...base(),
      "POST /api/v1/lessons/l1/reschedule": (body) => {
        attempts += 1;
        if (!(body as { override_conflicts: boolean }).override_conflicts) {
          return {
            status: 422,
            body: {
              type: "about:blank",
              title: "Nia Adeyemi already has Piano then.",
              status: 422,
              conflicts: [
                {
                  kind: "tutor_double_booked",
                  severity: "hard",
                  message: "Nia Adeyemi already has Piano then.",
                },
              ],
            },
          };
        }
        return { body: { lesson: LESSON, warnings: [] } };
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /GCSE Maths – Arjun Patel/ }), {
      detail: 0,
    });
    const dialog = await screen.findByRole("dialog", { name: /GCSE Maths/, hidden: true });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reschedule", hidden: true }));
    fireEvent.change(within(dialog).getByLabelText("From"), { target: { value: "17:00" } });
    fireEvent.change(within(dialog).getByLabelText("To"), { target: { value: "18:00" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Move lesson", hidden: true }));
    expect(
      await within(dialog).findByText("Nia Adeyemi already has Piano then."),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Schedule anyway", hidden: true }));
    await waitFor(() => expect(attempts).toBe(2));
    const last = calls.filter((c) => c.path.endsWith("/reschedule")).at(-1)?.body as {
      start: string;
    };
    expect(new Date(last.start).getHours()).toBe(17);
  });

  it("schedules a weekly series", async () => {
    window.history.pushState(null, "", "/calendar");
    const calls = mockApi({
      ...base(),
      "POST /api/v1/lesson-series": {
        status: 201,
        body: {
          series: { id: "ls1" },
          lessons_created: 10,
          lessons_changed: 0,
          skipped: [],
          conflicting: [],
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "New lesson" }));
    const dialog = await screen.findByRole("dialog", { name: "New lesson", hidden: true });
    const service = within(dialog).getByLabelText("Service");
    await waitFor(() =>
      expect(within(service).getAllByRole("option", { hidden: true })).toHaveLength(2),
    );
    fireEvent.change(service, { target: { value: "sv1" } });
    fireEvent.change(within(dialog).getByLabelText("Tutor"), { target: { value: "t1" } });
    fireEvent.change(within(dialog).getByLabelText("Student 1"), { target: { value: "s1" } });
    fireEvent.change(within(dialog).getByLabelText("Date"), { target: { value: "2026-11-02" } });
    fireEvent.change(within(dialog).getByLabelText("From"), { target: { value: "16:30" } });
    fireEvent.click(within(dialog).getByLabelText("Repeat weekly"));
    fireEvent.click(within(dialog).getByLabelText("Thursday"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Schedule series", hidden: true }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/lesson-series")?.body).toMatchObject({
        service: "sv1",
        start_date: "2026-11-02",
        start_time: "16:30",
        duration_minutes: 60,
        count: 10,
        attendees: [{ student: "s1" }],
        tutors: [{ tutor: "t1" }],
        conflict_mode: "skip",
      }),
    );
    const rrule = (calls.find((c) => c.path === "/api/v1/lesson-series")?.body as { rrule: string })
      .rrule;
    expect(rrule).toMatch(/^FREQ=WEEKLY;BYDAY=(MO|TU|WE|TH|FR|SA|SU)(,(MO|TU|WE|TH|FR|SA|SU))*$/);
    expect(rrule).toContain("TH");
  });

  it("switches to agenda and month views", async () => {
    window.history.pushState(null, "", "/calendar");
    mockApi(base());
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Agenda" }));
    const heading = await screen.findByRole("heading", {
      name: tuesday.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }),
    });
    expect(heading).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Month" }));
    expect(await screen.findByRole("table", { name: "Month" })).toBeInTheDocument();
  });
});

describe("availability", () => {
  it("saves weekly windows", async () => {
    window.history.pushState(null, "", "/availability");
    const calls = mockApi({
      ...base(),
      "GET /api/v1/availability/t1": {
        body: { effective_from: null, timezone: "Europe/London", windows: [] },
      },
      "PUT /api/v1/availability/t1": (body) => ({ body }),
      "GET /api/v1/time-off": { body: { results: [], next: null } },
    });
    render(<App />);
    await screen.findByText("No availability set yet.");
    fireEvent.click(screen.getByRole("button", { name: "Add a time" }));
    fireEvent.change(screen.getByLabelText("Day"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save availability" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        effective_from: toDateInput(new Date()),
        timezone: "Europe/London",
        windows: [{ weekday: 2, start_time: "16:00", end_time: "19:00", mode: "any" }],
      }),
    );
  });
});
