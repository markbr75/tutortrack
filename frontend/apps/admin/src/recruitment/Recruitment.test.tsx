import { fireEvent, render, screen } from "@testing-library/react";

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
    "compliance.view": "all",
  },
};

const BASE = {
  "GET /api/v1/me": { body: ADMIN },
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};

describe("recruitment", () => {
  it("approves an application", async () => {
    window.history.pushState(null, "", "/recruitment/a1");
    const application = {
      id: "a1", opening: null, opening_title: "", first_name: "Nia", last_name: "Okafor",
      full_name: "Nia Okafor", email: "nia@example.com", phone: "", postcode: "",
      subjects: [{ subject: "Maths" }], qualifications: "", experience: "3 years",
      right_to_work: "", video_url: "", cv: null, answers: { "Why tutoring?": "I love it" },
      stage: "s2", stage_name: "Interview", stage_entered_at: "2026-10-09T10:00:00Z",
      status: "open", owner: null, decision_reason: "", decided_at: null, tutor: null,
      created_at: "2026-10-08T10:00:00Z", scorecards: [], references: [], interviews: [],
    }; // prettier-ignore
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/applications/a1": { body: application },
      "GET /api/v1/application-stages": {
        body: [{ id: "s2", name: "Interview", order: 1, kind: "open", criteria: [],
                 reminder_days: null }],
      }, // prettier-ignore
      "POST /api/v1/applications/a1/approve": {
        body: { ...application, status: "hired", stage_name: "Hired" },
      },
    });
    render(<App />);
    expect(await screen.findByText(/I love it/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve and onboard" }));
    expect(await screen.findByText(/Hired/)).toBeInTheDocument();
    expect(calls.find((c) => c.path.endsWith("/approve"))?.body).toEqual({
      employment_type: "self_employed",
    });
  });

  it("shows the compliance matrix", async () => {
    window.history.pushState(null, "", "/compliance");
    mockApi({
      ...BASE,
      "GET /api/v1/compliance/dashboard": {
        body: {
          requirements: [{ id: "r1", key: "dbs_enhanced", name: "Enhanced DBS check" }],
          rows: [{ tutor: "t1", name: "Sam Lee", status: "restricted",
                   cells: { dbs_enhanced: { status: "expired", expiry_date: "2026-10-10" } } }],
        },
      }, // prettier-ignore
    });
    render(<App />);
    expect(await screen.findByText("Expired")).toBeInTheDocument();
    expect(screen.getByText(/Restricted/)).toBeInTheDocument();
  });

  it("lets a referee give a reference", async () => {
    window.history.pushState(null, "", "/references/tok");
    const page = { applicant: "Nia Okafor", status: "requested",
                   questions: ["How reliable are they?"], organisation: "Bright Minds" }; // prettier-ignore
    const calls = mockApi({
      "GET /api/v1/public/references/tok": { body: page },
      "POST /api/v1/public/references/tok": { body: { ...page, status: "received" } },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("How reliable are they?"), {
      target: { value: "Very" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send reference" }));
    expect(await screen.findByText("Thank you for your reference.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      responses: { q1: "Very" },
      rating: 4,
      concerns: false,
    });
  });
});
