import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const ADMIN = {
  ...ME,
  permissions: {
    ...ME.permissions,
    "recruitment.application.view": "all",
    "recruitment.application.edit": "all",
    "recruitment.application.decide": "all",
    "recruitment.pipeline.manage": "all",
    "recruitment.performance.view": "all",
    "recruitment.performance.manage": "all",
    "recruitment.offboarding.manage": "all",
    "compliance.view": "all",
    "compliance.verify": "all",
    "people.tutor.view": "all",
  },
};

const BASE = {
  "GET /api/v1/me": { body: ADMIN },
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};

const OPENING = {
  id: "o1",
  title: "Maths tutors in Leeds",
  slug: "maths-tutors-in-leeds",
  description: "",
  subjects: [{ subject: "Maths", level: "GCSE" }],
  location: "Leeds",
  branch: null,
  form: "f1",
  form_name: "Tutor application",
  published: true,
  closes_on: null,
  applications_open: 3,
};

describe("G5a recruitment", () => {
  it("lists openings and creates one with the standard form", async () => {
    window.history.pushState(null, "", "/recruitment/openings");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/job-openings": { body: [OPENING] },
      "GET /api/v1/forms": { body: [] },
      "GET /api/v1/branches": { body: { results: [], next: null } },
      "POST /api/v1/job-openings": { status: 201, body: { ...OPENING, id: "o2" } },
    });
    render(<App />);
    expect(await screen.findByText("Maths tutors in Leeds")).toBeInTheDocument();
    expect(screen.getByText("Maths GCSE")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View Maths tutors in Leeds" })).toHaveAttribute(
      "href",
      "/vacancies/maths-tutors-in-leeds",
    );
    fireEvent.click(screen.getByRole("button", { name: "New opening" }));
    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "English tutors" } });
    fireEvent.change(screen.getByLabelText(/^Subjects/), {
      target: { value: "English, Drama" },
    });
    fireEvent.click(screen.getByLabelText("Publish on the vacancies page"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      title: "English tutors",
      slug: "",
      description: "",
      subjects: ["English", "Drama"],
      location: "",
      branch: null,
      form: null,
      published: true,
      closes_on: null,
    });
  });

  it("filters the compliance matrix and asks tutors for missing documents", async () => {
    window.history.pushState(null, "", "/compliance");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/compliance/dashboard": {
        body: {
          requirements: [{ id: "r1", key: "dbs_enhanced", name: "Enhanced DBS check" }],
          rows: [
            {
              tutor: "t1",
              name: "Sam Lee",
              status: "active",
              cells: { dbs_enhanced: { status: "missing", expiry_date: null } },
            },
          ],
        },
      },
      "GET /api/v1/compliance/requirement-types": {
        body: [{ id: "r1", key: "dbs_enhanced", name: "Enhanced DBS check", active: true }],
      },
      "POST /api/v1/compliance/request-missing": {
        body: { count: 1, requests: [{ tutor: "t1", requirements: ["dbs_enhanced"] }] },
      },
    });
    render(<App />);
    expect(await screen.findByText("Missing")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Only tutors with gaps"));
    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.path === "/api/v1/compliance/dashboard" && c.search.includes("gaps=true"),
        ),
      ).toBe(true),
    );
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Sam Lee" }));
    fireEvent.click(screen.getByRole("button", { name: "Request documents from 1 tutor" }));
    expect(await screen.findByText("Asked 1 tutor for their documents.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      tutors: ["t1"],
      requirements: [],
    });
  });

  it("shows an applicant's CV and sends a booking link", async () => {
    window.history.pushState(null, "", "/recruitment/a1");
    const application = {
      id: "a1", opening: null, opening_title: "", first_name: "Nia", last_name: "Okafor",
      full_name: "Nia Okafor", email: "nia@example.com", phone: "", postcode: "",
      subjects: [{ subject: "Maths" }], qualifications: "", experience: "", right_to_work: "",
      video_url: "", cv: "f1", answers: {}, stage: "s2", stage_name: "Interview",
      stage_entered_at: "2026-10-09T10:00:00Z", status: "open", owner: null,
      decision_reason: "", decided_at: null, tutor: null, created_at: "2026-10-08T10:00:00Z",
      scorecards: [], references: [], interviews: [],
      cv_file: { id: "f1", filename: "Nia CV.pdf", content_type: "application/pdf",
                 size_bytes: 10, is_downloadable: true },
      video_file: null, attachments: [],
    }; // prettier-ignore
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/applications/a1": { body: application },
      "GET /api/v1/application-stages": {
        body: [{ id: "s2", name: "Interview", order: 1, kind: "open", criteria: [] }],
      },
      "POST /api/v1/applications/a1/interviews": { body: application },
    });
    render(<App />);
    expect(await screen.findByRole("button", { name: "CV: Nia CV.pdf" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-11-02" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-11-06" } });
    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/interviews"))).toBe(true));
    expect(calls.find((c) => c.path.endsWith("/interviews"))?.body).toEqual({
      mode: "availability",
      window_start: "2026-11-02",
      window_end: "2026-11-06",
      minutes: 30,
      options: [],
      meeting_url: "",
    });
  });

  it("records a probation review and starts offboarding on the tutor record", async () => {
    window.history.pushState(null, "", "/tutors/t1");
    const offboarding = {
      id: null, reason: "", leaving_on: null, started_at: null, completed_at: null, items: [],
      tutor_status: "active",
    }; // prettier-ignore
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/tutors/t1": {
        body: {
          id: "t1",
          full_name: "Nia Okafor",
          status: "active",
          has_joined: true,
          subjects: [],
        },
      },
      "GET /api/v1/notes": { body: { results: [], next: null } },
      "GET /api/v1/probation-reviews": {
        body: {
          results: [
            { id: "p1", tutor: "t1", tutor_name: "Nia Okafor", due_on: "2026-12-01",
              status: "scheduled", outcome_notes: "", reviewer: null, reviewer_name: "",
              reviewed_at: null, previous: null, created_at: "2026-09-01T09:00:00Z" },
          ],
          next: null,
        },
      }, // prettier-ignore
      "GET /api/v1/performance-notes": { body: { results: [], next: null } },
      "GET /api/v1/tutors/t1/offboarding": { body: offboarding },
      "POST /api/v1/probation-reviews/p1/complete": { body: {} },
      "POST /api/v1/tutors/t1/offboarding": {
        body: {
          ...offboarding,
          id: "x1",
          reason: "Moving abroad",
          started_at: "2026-10-21T09:00:00Z",
          tutor_status: "inactive",
          items: [
            { key: "jobs", label: "Reassign or end the tutor's jobs", auto: true, done: true,
              done_at: null },
            { key: "access", label: "Revoke access to TutorTrack", auto: true, done: false,
              done_at: null },
          ],
        },
      }, // prettier-ignore
    });
    render(<App />);
    // Performance and leaving sit on their own tab of the tutor record.
    fireEvent.click(await screen.findByRole("tab", { name: "Performance and leaving" }));
    expect(await screen.findByText(/Due on/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Review notes"), { target: { value: "Great start" } });
    fireEvent.click(screen.getByRole("button", { name: "Record outcome" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/complete"))).toBe(true));
    expect(calls.find((c) => c.path.endsWith("/complete"))?.body).toEqual({
      outcome: "passed",
      notes: "Great start",
      extend_to: null,
    });
    fireEvent.change(screen.getByLabelText("Reason for leaving"), {
      target: { value: "Moving abroad" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start offboarding" }));
    expect(await screen.findByRole("button", { name: "Revoke access" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finish offboarding" })).toBeDisabled();
  });

  it("uploads a CV on the public application form", async () => {
    window.history.pushState(null, "", "/vacancies/tutors");
    const calls = mockApi({
      "GET /api/v1/public/job-openings/tutors": {
        body: {
          title: "Tutors", slug: "tutors", description: "", location: "", subjects: [],
          closes_on: null, turnstile_site_key: "", organisation: "Bright Minds",
          schema: { steps: [{ title: "You", fields: [
            { key: "email", label: "Email", type: "email", maps_to: "applicant.email" },
            { key: "cv", label: "CV", type: "file", file_kind: "cv", maps_to: "applicant.cv" },
          ] }] },
        },
      }, // prettier-ignore
      "POST /api/v1/public/uploads": {
        status: 201,
        body: {
          token: "tok1",
          upload: { url: "https://s3.test/put", method: "PUT", headers: {}, expires_in: 900 },
          max_bytes: 10485760,
        },
      },
      "PUT /put": { body: {} },
      "POST /api/v1/public/uploads/complete": {
        body: { token: "tok1", filename: "cv.pdf", content_type: "application/pdf", size_bytes: 4 },
      },
      "POST /api/v1/public/job-openings/tutors": { status: 201, body: null },
    });
    render(<App />);
    const input = await screen.findByLabelText("CV");
    const file = new File(["%PDF"], "cv.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText("cv.pdf")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/public/uploads")?.body).toEqual({
      target: "opening",
      slug: "tutors",
      kind: "cv",
      filename: "cv.pdf",
      content_type: "application/pdf",
      size_bytes: 4,
    });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "n@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(
        calls.some((c) => c.path === "/api/v1/public/job-openings/tutors" && c.method === "POST"),
      ).toBe(true),
    );
    const apply = calls.find(
      (c) => c.path === "/api/v1/public/job-openings/tutors" && c.method === "POST",
    );
    expect((apply?.body as { data: Record<string, unknown> }).data).toEqual({
      email: "n@example.com",
      cv: "tok1",
    });
  });
});
