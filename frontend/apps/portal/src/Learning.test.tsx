import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "./App";
import { mockApi } from "./test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const ME = {
  role: "client",
  organisation: { name: "Bright Minds", primary_colour: "" },
  clients: [{ id: "c1", name: "The Patels" }],
  students: [{ id: "s1", name: "Arjun Patel" }],
  features: {
    cancellations: false, absence: false, invoices: false, reports: true, profile: false,
    booking: false, reschedule: false, classes: false, learning: true,
  },
  welcome_text: "", help_url: "", terms_url: "",
}; // prettier-ignore

const HOMEWORK = {
  id: "a1", title: "Fractions worksheet", instructions: "Questions 1-10", student: "s1",
  student_name: "Arjun Patel", tutor_name: "Nia Adeyemi", due_at: "2026-10-20T17:00:00Z",
  status: "assigned", overdue: false, can_submit: true, submission_type: "text",
  expected_minutes: 30, is_late: false, grade: "", feedback: "",
  resources: [{ id: "r1", title: "Fractions video", media_type: "youtube" }],
  attachments: [], submissions: [], quiz: null, quiz_result: null,
}; // prettier-ignore

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { membership: { role: "client" }, user: { email: "p@x.com" } } },
    "GET /api/v1/portal/me": { body: ME },
    "GET /api/v1/portal/dashboard": { body: { next_lessons: [], balance: [], reports: 0 } },
    ...extra,
  };
}

describe("goals in the family portal", () => {
  it("marks a milestone still to come with the pale dashed ring, not the missed ring", async () => {
    window.history.pushState(null, "", "/portal/learning");
    const goal = {
      id: "g1", student: "s1", student_name: "Arjun Patel", title: "Grade 7 in Maths",
      status: "active", progress_percent: 50, achieved_at: null, created_at: "2026-09-01T00:00:00Z",
      milestones: [
        { id: "m1", title: "Algebra", done: true },
        { id: "m2", title: "Geometry", done: false },
      ],
    }; // prettier-ignore
    mockApi(
      routes({
        "GET /api/v1/portal/learning/homework": { body: [] },
        "GET /api/v1/portal/learning/goals": { body: [goal] },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Goals" }));
    const open = (await screen.findByText("Geometry")).closest("li")!;
    expect(open).toHaveTextContent("(Not yet)");
    const ring = open.querySelector("circle")!;
    expect(ring.getAttribute("stroke-dasharray")).toBe("3 2.6");
    expect(ring.closest("svg")).toHaveClass("text-field");
    const done = screen.getByText("Algebra").closest("li")!;
    expect(done).toHaveTextContent("(Done)");
    expect(done.querySelector("circle")).toBeNull();
  });
});

describe("learning in the family portal", () => {
  it("lists homework and hands in a written answer", async () => {
    window.history.pushState(null, "", "/portal/learning");
    const calls = mockApi(
      routes({
        "GET /api/v1/portal/learning/homework": { body: [HOMEWORK] },
        "GET /api/v1/portal/learning/homework/a1": { body: HOMEWORK },
        "POST /api/v1/portal/learning/homework/a1/submit": {
          status: 201,
          body: { ...HOMEWORK, status: "submitted", can_submit: false },
        },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("link", { name: "Learning" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("link", { name: "Fractions worksheet" }));
    expect(await screen.findByText("Questions 1-10")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fractions video" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "1/2, 3/4" } });
    fireEvent.click(screen.getByRole("button", { name: "Hand in" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/submit"))?.body).toEqual({
        body: "1/2, 3/4",
        link: "",
        files: [],
      }),
    );
  });

  it("answers a quiz", async () => {
    window.history.pushState(null, "", "/portal/learning/homework/a1");
    const quiz = {
      ...HOMEWORK,
      submission_type: "quiz",
      quiz: {
        id: "q1", title: "Check", time_limit_minutes: null,
        questions: [
          { id: "x1", kind: "single", prompt: "Which equals 1/2?", points: 1,
            choices: [{ id: "a", text: "2/4" }, { id: "b", text: "2/3" }] },
          { id: "x2", kind: "multiple", prompt: "Bigger than 1/2?", points: 1,
            choices: [{ id: "a", text: "3/4" }, { id: "b", text: "1/3" }] },
        ],
      },
    }; // prettier-ignore
    const calls = mockApi(
      routes({
        "GET /api/v1/portal/learning/homework/a1": { body: quiz },
        "POST /api/v1/portal/learning/homework/a1/submit": { status: 201, body: HOMEWORK },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("radio", { name: "2/4" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "3/4" }));
    fireEvent.click(screen.getByRole("button", { name: "Hand in" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/submit"))?.body).toMatchObject({
        quiz_answers: { x1: "a", x2: ["a"] },
      }),
    );
  });

  it("shows results as a trend with a table view", async () => {
    window.history.pushState(null, "", "/portal/learning?tab=results");
    mockApi(
      routes({
        "GET /api/v1/portal/learning/results": {
          body: [
            { id: "r1", name: "Mock", kind: "mock_exam", subject: "Maths", student: "s1",
              student_name: "Arjun Patel", date: "2026-10-01", score: "54.00",
              max_score: "80.00", percent: "67.50", grade: "6" },
          ],
        }, // prettier-ignore
      }),
    );
    render(<App />);
    expect(
      await screen.findByRole("img", { name: "Arjun Patel: scores over time" }),
    ).toBeInTheDocument();
    expect(screen.getByText("67.50% (6)")).toBeInTheDocument();
  });
});

describe("learning in the tutor app", () => {
  const TUTOR = {
    "GET /api/v1/me": { body: { membership: { role: "tutor" }, user: { email: "n@x.com" } } },
    "GET /api/v1/tutor/me": {
      body: { id: "t1", name: "Nia", email: "n@x.com", can_cancel: true,
              can_edit_lessons: false, can_see_pay: false },
    }, // prettier-ignore
    "GET /api/v1/tutor/students": {
      body: [{ id: "s1", name: "Arjun Patel", year_group: "", jobs: [], next_lesson: null }],
    },
  };

  it("lists work to review and sets homework", async () => {
    window.history.pushState(null, "", "/portal/tutor/homework");
    const calls = mockApi({
      ...TUTOR,
      "GET /api/v1/learning/homework-assignments": {
        body: {
          results: [
            { id: "a1", homework_title: "Fractions worksheet", student_name: "Arjun Patel" },
          ],
          next: null,
          previous: null,
        },
      },
      "POST /api/v1/learning/homework": { status: 201, body: {} },
    });
    render(<App />);
    expect(
      await screen.findByRole("link", { name: "Fractions worksheet · Arjun Patel" }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Ratio" } });
    fireEvent.change(screen.getByLabelText("Student"), { target: { value: "s1" } });
    fireEvent.change(screen.getByLabelText("Due"), { target: { value: "2026-11-01T18:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Set homework" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        title: "Ratio",
        students: ["s1"],
        submission_type: "text",
      }),
    );
  });
});
