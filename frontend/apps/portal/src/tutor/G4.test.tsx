import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const later = new Date(Date.now() + 3 * 86400_000);
later.setHours(10, 0, 0, 0);
const laterEnd = new Date(later.getTime() + 3600_000);

function routes(me: Record<string, boolean>, extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": {
      body: { membership: { role: "tutor" }, user: { email: "nia@example.com" } },
    },
    "GET /api/v1/tutor/me": {
      body: {
        id: "t1",
        name: "Nia Adeyemi",
        email: "nia@example.com",
        can_cancel: false,
        can_edit_lessons: false,
        can_create_lessons: false,
        can_reschedule: true,
        can_see_pay: true,
        ...me,
      },
    },
    ...extra,
  };
}

const lesson = {
  id: "l1",
  title: "GCSE Maths – Arjun",
  start: later.toISOString(),
  end: laterEnd.toISOString(),
  status: "planned",
  online: false,
  notes_for_tutor: "",
  attendees: [{ id: "a1", student: "s1", name: "Arjun Patel", outcome: "" }],
};

describe("tutor app: planning, previous report, history and dictation (G4)", () => {
  it("books a lesson after checking for clashes", async () => {
    window.history.pushState(null, "", "/portal/tutor/schedule");
    const calls = mockApi(
      routes(
        { can_create_lessons: true },
        {
          "GET /api/v1/calendar": { body: [] },
          "GET /api/v1/tutor/jobs": {
            body: [
              {
                id: "j1",
                name: "Arjun Maths",
                service: "Maths 1:1",
                duration_minutes: 60,
                online: false,
                location: "",
                students: [{ id: "s1", name: "Arjun Patel" }],
              },
            ],
          },
          "POST /api/v1/tutor/lessons/check": {
            body: [
              {
                kind: "tutor_unavailable",
                severity: "soft",
                message: "Outside your availability",
                lesson_id: null,
                tutor_id: "t1",
                student_id: null,
              },
            ],
          },
          "POST /api/v1/tutor/lessons": {
            status: 422,
            body: {
              type: "about:blank",
              title: "Conflict",
              status: 422,
              detail: "Nia is teaching then",
              conflicts: [
                {
                  kind: "tutor_busy",
                  severity: "hard",
                  message: "Nia is teaching then",
                  lesson_id: "l9",
                  tutor_id: "t1",
                  student_id: null,
                },
              ],
            },
          },
        },
      ),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Plan a lesson" }));
    fireEvent.change(await screen.findByLabelText(/Job/), { target: { value: "j1" } });
    fireEvent.change(screen.getByLabelText(/Starts/), { target: { value: "2026-11-02T10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Check for clashes" }));
    expect(await screen.findByText("Outside your availability")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Book lesson" }));
    expect(await screen.findByText("This time clashes:")).toBeInTheDocument();
    const booked = calls.find((c) => c.method === "POST" && c.path === "/api/v1/tutor/lessons");
    expect(booked?.body).toMatchObject({ job: "j1" });
  });

  it("moves a lesson directly, or asks when tutors can't reschedule", async () => {
    window.history.pushState(null, "", "/portal/tutor/lessons/l1");
    const calls = mockApi(
      routes(
        { can_reschedule: false },
        {
          "GET /api/v1/lessons/l1": { body: lesson },
          "GET /api/v1/tutor/lessons/l1/previous-report": {
            body: {
              report: {
                id: "r0",
                lesson_id: "l0",
                lesson_title: "GCSE Maths – Arjun",
                lesson_start: "2026-10-01T09:00:00Z",
                tutor: "Nia Adeyemi",
                status: "submitted",
                answers: [{ key: "summary", label: "Summary", value: "Fractions secure" }],
              },
            },
          },
          "POST /api/v1/lessons/l1/reschedule-requests": { status: 201, body: { id: "rr1" } },
        },
      ),
    );
    render(<App />);
    expect(await screen.findByText(/Previous report/)).toBeInTheDocument();
    expect(screen.getByText("Fractions secure")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ask to move" }));
    fireEvent.change(screen.getByLabelText(/New start time/), {
      target: { value: "2026-11-03T11:00" },
    });
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "Exams" } });
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByText("Request sent.")).toBeInTheDocument();
    const asked = calls.find((c) => c.path === "/api/v1/lessons/l1/reschedule-requests");
    expect(asked?.body).toMatchObject({ reason: "Exams" });
  });

  it("shows a student's lesson history", async () => {
    window.history.pushState(null, "", "/portal/tutor/students/s1");
    mockApi(
      routes(
        {},
        {
          "GET /api/v1/tutor/students/s1/lessons": {
            body: {
              student: { id: "s1", name: "Arjun Patel", year_group: "Year 10" },
              attendance_percent: 90,
              lessons: [
                {
                  id: "l0",
                  title: "GCSE Maths – Arjun",
                  service: "Maths 1:1",
                  start: "2026-10-01T09:00:00Z",
                  end: "2026-10-01T10:00:00Z",
                  status: "completed",
                  outcome: "present",
                  report_id: "r0",
                  report_status: "submitted",
                },
              ],
            },
          },
        },
      ),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Arjun Patel" })).toBeInTheDocument();
    expect(screen.getByText("Attended 90% of recorded lessons")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Submitted" })).toHaveAttribute(
      "href",
      "/portal/tutor/reports/r0",
    );
  });

  it("dictates into a report field where the browser supports it", async () => {
    class FakeRecognition {
      lang = "";
      continuous = false;
      interimResults = false;
      onresult: ((e: unknown) => void) | null = null;
      onerror: ((e: unknown) => void) | null = null;
      onend: (() => void) | null = null;
      start() {
        setTimeout(
          () =>
            this.onresult?.({
              resultIndex: 0,
              results: [{ isFinal: true, 0: { transcript: "Great focus today" } }],
            }),
          0,
        );
      }
      stop() {
        this.onend?.();
      }
    }
    vi.stubGlobal("webkitSpeechRecognition", FakeRecognition);
    const { ReportFieldInput } = await import("./ReportPage");
    const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
    mockApi({});
    let value = "Arjun worked hard.";
    const onChange = vi.fn((v: unknown) => {
      value = String(v);
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ReportFieldInput
          field={{ key: "summary", label: "Summary", type: "text", required: false } as never}
          value={value}
          onChange={onChange}
          disabled={false}
        />
      </QueryClientProvider>,
    );
    const button = screen.getByRole("button", { name: "Dictate Summary" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(button);
    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith("Arjun worked hard. Great focus today"),
    );
  });

  it("hides dictation where the browser has no speech recognition", async () => {
    const { ReportFieldInput } = await import("./ReportPage");
    const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
    mockApi({});
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ReportFieldInput
          field={{ key: "summary", label: "Summary", type: "text", required: false } as never}
          value=""
          onChange={() => undefined}
          disabled={false}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByLabelText("Summary")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dictate/ })).not.toBeInTheDocument();
  });

  it("lets a tutor choose digest emails", async () => {
    window.history.pushState(null, "", "/portal/tutor/notifications");
    const calls = mockApi(
      routes(
        {},
        {
          "GET /api/v1/digest-preferences/mine": {
            body: [
              {
                kind: "tutor_agenda",
                label: "Daily agenda",
                enabled: true,
                org_enabled: true,
                send_time: "07:00",
                weekday: null,
                customised: false,
              },
            ],
          },
          "PUT /api/v1/digest-preferences/mine": (body) => ({ body }),
        },
      ),
    );
    render(<App />);
    const time = await screen.findByLabelText("Time");
    fireEvent.change(time, { target: { value: "06:30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save digest choices" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual([
        { kind: "tutor_agenda", enabled: true, send_time: "06:30", weekday: null },
      ]),
    );
  });
});
