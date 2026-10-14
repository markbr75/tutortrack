import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const REPORT = {
  id: "r1",
  lesson: "l1",
  lesson_title: "GCSE Maths – Arjun",
  status: "pending",
  answers: {},
  returned_note: "",
  template_fields: [
    {
      key: "covered",
      label: "What we covered",
      type: "rich_text",
      required: true,
      visibility: "student",
    },
    {
      key: "homework",
      label: "Homework",
      type: "homework",
      required: false,
      visibility: "student",
    },
  ],
};

const STATUS = {
  available: true,
  provider: "fake",
  features: { lesson_report: true, content: true },
  credits_exhausted: false,
  credits: null,
};

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": {
      body: { membership: { role: "tutor" }, user: { email: "nia@example.com" } },
    },
    "GET /api/v1/tutor/me": {
      body: {
        id: "t1",
        name: "Nia",
        email: "nia@example.com",
        can_cancel: true,
        can_edit_lessons: false,
        can_see_pay: true,
      },
    },
    "GET /api/v1/ai/status": { body: STATUS },
    "GET /api/v1/lesson-reports/r1": { body: REPORT },
    ...extra,
  };
}

describe("AI lesson report drafting (FR-31-1)", () => {
  it("drafts from notes, fills the form and flags the submitted report as AI-assisted", async () => {
    window.history.pushState(null, "", "/portal/tutor/reports/r1");
    const calls = mockApi(
      routes({
        "POST /api/v1/ai/lesson-reports/r1/draft": {
          body: {
            request: "req1",
            answers: {
              covered: "Arjun added fractions with unlike denominators.",
              homework: "Worksheet 4",
            },
            suggested_topics: [{ id: "n1", name: "Number > Fractions" }],
            homework: "Worksheet 4",
            transcript: "",
          },
        },
        "POST /api/v1/lesson-reports/r1/submit": { body: { ...REPORT, status: "submitted" } },
        "POST /api/v1/ai/assists": {
          status: 201,
          body: { id: "a1", request: "req1", subject_type: "lesson_report", subject_id: "r1" },
        },
      }),
    );
    render(<App />);
    const drafter = await screen.findByRole("region", { name: "Draft with AI" });
    fireEvent.change(within(drafter).getByLabelText("Rough notes"), {
      target: { value: "fractions unlike denominators, good effort, hw ws4" },
    });
    fireEvent.click(within(drafter).getByRole("button", { name: "Draft the report" }));
    expect(
      await within(drafter).findByText(/Suggested topics: Number > Fractions/),
    ).toBeInTheDocument();
    const covered = screen.getByLabelText("What we covered *");
    await waitFor(() =>
      expect(covered).toHaveValue("Arjun added fractions with unlike denominators."),
    );
    fireEvent.click(screen.getByRole("button", { name: "Submit report" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/ai/assists")?.body).toEqual({
        request: "req1",
        subject_type: "lesson_report",
        subject_id: "r1",
      }),
    );
    const draft = calls.find((c) => c.path.endsWith("/draft"));
    expect(String(draft?.body)).toContain("fractions unlike denominators");
  });

  it("is hidden when the organisation hasn't turned it on", async () => {
    window.history.pushState(null, "", "/portal/tutor/reports/r1");
    mockApi(
      routes({
        "GET /api/v1/ai/status": {
          body: { ...STATUS, features: { lesson_report: false, content: false } },
        },
      }),
    );
    render(<App />);
    await screen.findByLabelText("What we covered *");
    expect(screen.queryByRole("region", { name: "Draft with AI" })).toBeNull();
  });
});
