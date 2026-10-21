import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const BASE = {
  "GET /api/v1/me": { body: { membership: { role: "tutor" }, user: { email: "n@x.com" } } },
  "GET /api/v1/tutor/me": {
    body: {
      id: "t1",
      name: "Nia",
      email: "n@x.com",
      can_cancel: true,
      can_edit_lessons: false,
      can_see_pay: true,
    },
  },
};

const TEST = {
  id: "q1",
  title: "Maths screening",
  description: "",
  subject: "Maths",
  level: "",
  pass_percent: 50,
  time_limit_minutes: null,
  question_count: 2,
  subjects: ["Maths GCSE"],
  status: "not_taken",
  percent: null,
  taken_at: null,
  retake_at: null,
  can_take: true,
};

describe("tutor subject tests (G5a)", () => {
  it("takes a test and shows the result", async () => {
    window.history.pushState(null, "", "/portal/tutor/tests");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/me/subject-tests": { body: [TEST] },
      "GET /api/v1/me/subject-tests/q1": {
        body: {
          ...TEST,
          questions: [
            {
              id: "a",
              kind: "single",
              prompt: "2 + 2?",
              choices: [
                { id: "x", text: "3" },
                { id: "y", text: "4" },
              ],
              points: 1,
            },
            { id: "b", kind: "short", prompt: "Square root of 81?", choices: [], points: 1 },
          ],
        },
      },
      "POST /api/v1/me/subject-tests/q1": {
        body: { percent: "100.00", passed: true, pass_percent: 50, assessed: ["Maths GCSE"] },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Start Maths screening" }));
    fireEvent.click(await screen.findByLabelText("4"));
    fireEvent.change(screen.getByLabelText("Your answer"), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Send answers" }));
    expect(await screen.findByText("Well done: you scored 100%.")).toBeInTheDocument();
    expect(screen.getByText(/Marked as assessed: Maths GCSE/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      answers: { a: "y", b: "9" },
    });
  });

  it("shows when a failed test can be retaken", async () => {
    window.history.pushState(null, "", "/portal/tutor/tests");
    mockApi({
      ...BASE,
      "GET /api/v1/me/subject-tests": {
        body: [
          {
            ...TEST,
            status: "failed",
            percent: "40.00",
            can_take: false,
            retake_at: "2026-10-28T09:00:00Z",
          },
        ],
      },
    });
    render(<App />);
    expect(await screen.findByText(/you can try again from/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Maths screening/ })).not.toBeInTheDocument();
  });
});
