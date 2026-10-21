import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const BASE = {
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};
const COORDINATOR = {
  ...ME,
  permissions: {
    ...ME.permissions,
    "jobs.job.view": "all",
    "matching.search": "all",
    "people.tutor.view": "all",
    "people.tutor.edit": "all",
  },
};
const factor = (score: number, value: unknown = null) => ({
  weight: 10,
  score,
  value,
  known: true,
});
const RESULT = (needs: Record<string, unknown>) => ({
  query: "q1", criteria: {}, origin: null,
  needs: { exam_boards: [], sen_tags: [], gender: "", gender_preference_enabled: true, ...needs },
  results: [{
    rank: 1, tutor: { id: "t1", name: "Nia Okafor", headline: "", status: "active" },
    score: "80.0", breakdown: { exam_board: factor(1, "AQA"), sen: factor(0.5, "1/2") },
    distance_km: null, slot_fit: [], restricted: false, reasons: [], point: null,
    shortlisted: false,
  }],
}); // prettier-ignore

describe("matching on students' needs (gap G5c, FR-19-1)", () => {
  it("shows the job's needs and searches again with changes", async () => {
    window.history.pushState(null, "", "/jobs/j1/match");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/me": { body: COORDINATOR },
      "GET /api/v1/jobs/j1": { body: { id: "j1", name: "Arjun Maths", default_schedule: [] } },
      "POST /api/v1/matching/search": (body) => ({
        body: RESULT(
          (body as { exam_boards?: string[] }).exam_boards
            ? { exam_boards: (body as { exam_boards: string[] }).exam_boards }
            : { exam_boards: ["AQA"], sen_tags: ["Dyslexia", "ADHD"] },
        ),
      }),
      "GET /api/v1/job-offer-batches": { body: { results: [], next: null, previous: null } },
      "GET /api/v1/job-postings": { body: { results: [], next: null, previous: null } },
    });
    render(<App />);
    const boards = await screen.findByLabelText("Exam boards");
    expect(boards).toHaveValue("AQA");
    expect(screen.getByLabelText("Special educational needs")).toHaveValue("Dyslexia, ADHD");
    fireEvent.click(screen.getByText("Score breakdown"));
    expect(screen.getByText("Exam board")).toBeInTheDocument();
    expect(screen.getByText("SEN experience")).toBeInTheDocument();
    fireEvent.change(boards, { target: { value: "OCR, Edexcel" } });
    fireEvent.change(screen.getByLabelText("Tutor gender preference"), {
      target: { value: "female" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search again" }));
    await vi.waitFor(() =>
      expect(calls.filter((c) => c.path === "/api/v1/matching/search").at(-1)?.body).toEqual({
        job: "j1",
        include_restricted: false,
        limit: 50,
        exam_boards: ["OCR", "Edexcel"],
        sen_tags: ["Dyslexia", "ADHD"],
        gender: "female",
      }),
    );
  });

  it("edits a tutor's matching profile", async () => {
    window.history.pushState(null, "", "/tutors/t1");
    const tutor = {
      id: "t1", email: "nia@example.com", first_name: "Nia", last_name: "Okafor",
      display_name: "", full_name: "Nia Okafor", phone: "", headline: "", status: "active",
      has_joined: true, subjects: [], qualifications: [], delivers_online: true,
      delivers_in_person: true, sen_tags: ["Dyslexia"], exam_boards: [], gender: "",
    }; // prettier-ignore
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/me": { body: COORDINATOR },
      "GET /api/v1/tutors/t1": { body: tutor },
      "PATCH /api/v1/tutors/t1": (body) => ({ body: { ...tutor, ...(body as object) } }),
    });
    render(<App />);
    const card = await screen.findByRole("region", { name: "Matching profile" });
    expect(card).toHaveTextContent("Dyslexia");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Exam boards"), { target: { value: "AQA, OCR" } });
    fireEvent.change(screen.getByLabelText("Gender"), { target: { value: "female" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
        sen_tags: ["Dyslexia"],
        exam_boards: ["AQA", "OCR"],
        gender: "female",
        invite: false,
      }),
    );
  });
});
