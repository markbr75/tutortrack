import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "./App";
import { mockApi } from "./test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const started = new Date(Date.now() - 2 * 3600_000).toISOString();
const ended = new Date(Date.now() - 3600_000).toISOString();

function tutor(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { membership: { role: "tutor" }, user: { email: "n@x.com" } } },
    "GET /api/v1/tutor/me": {
      body: { id: "t1", name: "Nia", email: "n@x.com", can_cancel: false,
              can_edit_lessons: false, can_see_pay: true },
    }, // prettier-ignore
    ...extra,
  };
}

function family(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/portal/me": {
      body: {
        role: "client", organisation: { name: "Bright Minds", primary_colour: "" },
        clients: [{ id: "c1", name: "The Patels" }], students: [{ id: "s1", name: "Arjun" }],
        features: { reports: true }, welcome_text: "", help_url: "", terms_url: "",
      },
    }, // prettier-ignore
    ...extra,
  };
}

const ROOM = {
  lesson_id: "l1", title: "GCSE Maths", start: started, end: ended, role: "family",
  provider: "builtin", embeddable: true, join_url: "https://bm.daily.co/tt-room",
  opens_at: started, open: true, safeguarding_banner: "Tell a trusted adult if worried.",
  recording: true, consent_needed: ["s1"], resources: [{ id: "r1", title: "Past paper 1" }],
}; // prettier-ignore

describe("Phase 3 portal (ADR 0032)", () => {
  it("fills in the tutor's register from the online lesson", async () => {
    window.history.pushState(null, "", "/portal/tutor/lessons/l1");
    mockApi(
      tutor({
        "GET /api/v1/lessons/l1": {
          body: { id: "l1", title: "GCSE Maths", start: started, end: ended, status: "planned",
                  online: true, meeting_url: "https://x.test/room", notes_for_tutor: "",
                  attendees: [{ id: "a1", name: "Arjun Patel", outcome: "" }] },
        }, // prettier-ignore
        "GET /api/v1/lessons/l1/video-attendance": {
          body: { available: true, actual_minutes: 50, tutor_minutes: 60, guests: 0,
                  students: [{ attendee_id: "a1", student_id: "s1", name: "Arjun Patel",
                               suggested_outcome: "late", late_minutes: 8,
                               minutes_attended: 50, first_joined_at: started,
                               last_left_at: ended }] },
        }, // prettier-ignore
        "GET /api/v1/recordings": { body: { results: [], next: null, previous: null } },
      }),
    );
    render(<App />);
    const register = await screen.findByRole("form", { name: "Register" });
    fireEvent.click(
      await within(register).findByRole("button", { name: "Fill in the register from this" }),
    );
    expect(within(register).getByLabelText("Attendance for Arjun Patel")).toHaveValue("late");
    expect(within(register).getByLabelText("Minutes late")).toHaveValue(8);
    expect(screen.getByText("The lesson ran for 50 minutes.")).toBeInTheDocument();
  });

  it("embeds the classroom with the safeguarding banner and asks for recording consent", async () => {
    window.history.pushState(null, "", "/portal/classroom/l1");
    const calls = mockApi(
      family({
        "GET /api/v1/lessons/l1/classroom": { body: ROOM },
        "POST /api/v1/lessons/l1/classroom/consent": { body: { consented: ["s1"] } },
      }),
    );
    render(<App />);
    expect(await screen.findByTitle("Online classroom: GCSE Maths")).toHaveAttribute(
      "src",
      "https://bm.daily.co/tt-room",
    );
    expect(screen.getByText("Tell a trusted adult if worried.")).toBeInTheDocument();
    expect(screen.getByText("Past paper 1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "I agree to recording" }));
    await vi.waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/lessons/l1/classroom/consent")).toBe(true),
    );
  });

  it("shows the tutor the link to complete an online background check", async () => {
    window.history.pushState(null, "", "/portal/tutor/compliance");
    mockApi(
      tutor({
        "GET /api/v1/me/compliance": { body: { restricted: false, requirements: [], records: [] } },
        "GET /api/v1/me/background-checks": {
          body: [{ id: "b1", provider: "ucheck", provider_label: "uCheck (DBS checks)",
                   package: "enhanced", status: "invited", result: "",
                   invite_url: "https://checks.example.test/invite/x",
                   created_at: started, completed_at: null }],
        }, // prettier-ignore
      }),
    );
    render(<App />);
    expect(await screen.findByRole("link", { name: "Complete your check" })).toHaveAttribute(
      "href",
      "https://checks.example.test/invite/x",
    );
    expect(screen.getByText(/uCheck \(DBS checks\): Waiting for the tutor/)).toBeInTheDocument();
  });
});
