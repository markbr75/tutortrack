import { fireEvent, render, screen, waitFor } from "@testing-library/react";

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
  permissions: Object.fromEntries(
    [
      "team.view",
      "learning.homework.view",
      "learning.homework.manage",
      "learning.homework.review",
      "learning.resource.view",
      "learning.resource.manage",
      "learning.resource.share",
      "learning.curriculum.view",
      "learning.mastery.edit",
      "learning.goal.view",
      "learning.goal.manage",
      "learning.assessment.view",
    ].map((k) => [k, "all"]),
  ),
};

const page = (results: unknown[]) => ({ body: { results, next: null, previous: null } });

const ASSIGNMENT = {
  id: "a1", homework: "h1", homework_title: "Fractions worksheet", submission_type: "text",
  student: "s1", student_name: "Arjun Patel", status: "submitted", round: 1,
  due_at: "2026-10-20T17:00:00Z", submitted_at: "2026-10-19T17:00:00Z", is_late: false,
  completed_at: null, grade: "", score_percent: null, feedback: "", reviewed_at: null,
  reminded_at: null, overdue_at: null,
  submissions: [{ id: "sub1", attempt: 1, body: "1/2 and 3/4", link: "", files: [],
                  quiz_attempt: null, submitted_by_name: "Parent", is_late: false,
                  created_at: "2026-10-19T17:00:00Z" }],
}; // prettier-ignore

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: COORDINATOR },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/students": page([{ id: "s1", full_name: "Arjun Patel" }]),
    "GET /api/v1/learning/quizzes": page([]),
    ...extra,
  };
}

describe("learning tools", () => {
  it("reviews handed-in homework", async () => {
    window.history.pushState(null, "", "/learning");
    const calls = mockApi(
      routes({
        "GET /api/v1/learning/homework": page([]),
        "GET /api/v1/learning/homework-assignments": page([ASSIGNMENT]),
        "POST /api/v1/learning/homework-assignments/a1/review": {
          body: { ...ASSIGNMENT, status: "completed", grade: "7" },
        },
      }),
    );
    render(<App />);
    const card = await screen.findByRole("article", { name: "Fractions worksheet – Arjun Patel" });
    expect(card).toHaveTextContent("1/2 and 3/4");
    fireEvent.change(screen.getByLabelText("Grade"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Feedback"), { target: { value: "Great work" } });
    fireEvent.click(screen.getByRole("button", { name: "Mark complete" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/review"))?.body).toEqual({
        outcome: "complete",
        grade: "7",
        feedback: "Great work",
      }),
    );
    expect(screen.getByRole("form", { name: "Set homework" })).toBeInTheDocument();
  });

  it("shares a resource with a student", async () => {
    window.history.pushState(null, "", "/learning");
    const calls = mockApi(
      routes({
        "GET /api/v1/learning/homework": page([]),
        "GET /api/v1/learning/homework-assignments": page([]),
        "GET /api/v1/learning/storage": {
          body: { used_bytes: 1073741824, library_bytes: 0, limit_gb: 5 },
        },
        "GET /api/v1/learning/resources": page([
          {
            id: "r1", title: "Ratio video", description: "", kind: "link", file: null,
            file_name: "", file_size: null, url: "https://youtu.be/x", media_type: "youtube",
            folder: null, owner: null, owner_name: "", subject: null, level: null, topics: [],
            tags: ["ratio"], visibility: "tutors", share_count: 0, archived_at: null,
            created_at: "2026-10-01T10:00:00Z",
          },
        ]), // prettier-ignore
        "POST /api/v1/learning/resources/r1/share": { status: 201, body: [] },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Resources" }));
    expect(await screen.findByText("Storage used: 1.00 GB of 5 GB")).toBeInTheDocument();
    expect(screen.getByText("YouTube")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Share Ratio video with"), {
      target: { value: "s1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Share" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/share"))?.body).toEqual({ students: ["s1"] }),
    );
  });

  it("shows a student's coverage, score trend and goals", async () => {
    window.history.pushState(null, "", "/learning/students/s1");
    const calls = mockApi(
      routes({
        "GET /api/v1/students/s1": { body: { id: "s1", full_name: "Arjun Patel" } },
        "GET /api/v1/learning/homework-assignments/stats": {
          body: { total: 4, submitted: 3, completed: 2, late: 1, due: 4, overdue: 1, on_time: 2,
                  completion_rate: "75.0" },
        }, // prettier-ignore
        "GET /api/v1/learning/students/s1/coverage": {
          body: [
            {
              curriculum: { id: "c1", name: "GCSE Mathematics" },
              units: [{ id: "u1", name: "Number", topics: [
                { id: "t1", name: "Fractions", code: "U1.3", level: "secure", lessons: 2,
                  last_covered: "2026-10-10T10:00:00Z" },
              ] }],
              summary: { not_started: 0, learning: 0, secure: 1, mastered: 0 },
              covered: 1,
              topics: 1,
            },
          ],
        }, // prettier-ignore
        "GET /api/v1/learning/students/s1/trend": {
          body: [
            { date: "2026-09-01", percent: "50.00", grade: "5", name: "Diagnostic",
              kind: "diagnostic", subject: "" },
            { date: "2026-10-01", percent: "67.50", grade: "6", name: "Mock",
              kind: "mock_exam", subject: "" },
          ],
        }, // prettier-ignore
        "GET /api/v1/learning/goals": page([
          {
            id: "g1", student: "s1", student_name: "Arjun Patel", kind: "target_grade",
            title: "Grade 7", description: "", subject: null, target_grade: "7",
            current_grade: "", exam_date: null, due_date: null, status: "active",
            progress_percent: 50, achieved_at: null, visible_to_family: true,
            milestones: [{ id: "m1", title: "Mock", due_date: null, done: true, done_at: "x" },
                         { id: "m2", title: "Algebra", due_date: null, done: false, done_at: null }],
            created_at: "2026-10-01T10:00:00Z",
          },
        ]), // prettier-ignore
        "POST /api/v1/learning/goals/g1/milestone": { body: {} },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Arjun Patel: learning")).toBeInTheDocument();
    expect(screen.getByText("Secure · 2 lessons")).toBeInTheDocument();
    expect(
      screen.getByText("Homework handed in on time: 75.0% of 4 due (1 overdue)."),
    ).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Score trend" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Mock, .*: 67.50%/ })).toBeInTheDocument();
    // Goal progress is said in words, not drawn as a bar.
    expect(screen.getByText("In progress · 50% done · 1 of 2 milestones")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Algebra" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/milestone"))?.body).toEqual({
        milestone: "m2",
        done: true,
      }),
    );
  });
});
