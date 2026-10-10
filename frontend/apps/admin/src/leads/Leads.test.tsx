import { fireEvent, render, screen } from "@testing-library/react";

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
  permissions: {
    ...ME.permissions,
    "leads.enquiry.view": "all",
    "leads.enquiry.edit": "all",
    "leads.enquiry.create": "all",
  },
};

const STAGES = [
  { id: "s1", name: "New", order: 0, kind: "open", probability: 10, sla_hours: 24, colour: "" },
  { id: "s2", name: "Contacted", order: 1, kind: "open", probability: 30, sla_hours: 72, colour: "" },
]; // prettier-ignore

const ENQUIRY = {
  id: "e1", title: "Priya Patel - Maths", client: "c1", client_name: "The Patels",
  contact: "ct1", contact_name: "Priya Patel", contact_email: "p@example.com", contact_phone: "",
  students: ["st1"], student_names: ["Arjun"], pipeline: "p1", stage: "s1", stage_name: "New",
  stage_entered_at: "2026-10-09T10:00:00Z", status: "open", owner: null, owner_name: "",
  priority: "normal", subjects: [{ subject: "Maths", level: "" }], notes: "",
  value_estimate: null, expected_start: null, source: "form", source_detail: "Enquire",
  utm: {}, first_response_at: null, sla_breached: true, lost_reason: "", lost_note: "",
  won_at: null, lost_at: null, trial_lesson: null, trial_outcome: "", trial_feedback: "",
  converted_job_ids: [], created_at: "2026-10-08T10:00:00Z", age_hours: 50,
}; // prettier-ignore

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: COORDINATOR },
    "GET /api/v1/organisation": { body: { status: "active" } },
    "GET /api/v1/me/organisations": { body: [] },
    ...extra,
  };
}

describe("enquiries", () => {
  it("shows the board and moves a card from the keyboard", async () => {
    window.history.pushState(null, "", "/leads");
    const calls = mockApi(
      routes({
        "GET /api/v1/pipelines": {
          body: [{ id: "p1", name: "Enquiries", is_default: true, active: true, stages: STAGES }],
        },
        "GET /api/v1/enquiries/board": {
          body: [
            { stage: STAGES[0], enquiries: [ENQUIRY] },
            { stage: STAGES[1], enquiries: [] },
          ],
        },
        "POST /api/v1/enquiries/e1/move": { body: { ...ENQUIRY, stage: "s2" } },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("link", { name: "Priya Patel - Maths" })).toBeInTheDocument();
    expect(screen.getByText("Waiting too long")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Move Priya Patel - Maths to"), {
      target: { value: "s2" },
    });
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/move"))?.body).toEqual({ stage: "s2" }),
    );
  });

  it("lets a family fill in the hosted form", async () => {
    window.history.pushState(null, "", "/f/enquire?utm_source=google");
    const calls = mockApi({
      "GET /api/v1/public/forms/enquire": {
        body: {
          name: "Tell us about your child", type: "enquiry", thank_you: "", redirect_url: "",
          consent_text: "", turnstile_site_key: "", organisation: "Bright Minds",
          schema: {
            steps: [
              {
                title: "You",
                fields: [
                  { key: "first_name", label: "First name", type: "text", required: true },
                  { key: "email", label: "Email", type: "email", required: true },
                  { key: "children", label: "Children", type: "students", required: true },
                ],
              },
            ],
          },
        },
      }, // prettier-ignore
      "POST /api/v1/public/forms/enquire": { status: 201, body: { ok: true, pay_url: "" } },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText(/^First name/), { target: { value: "Priya" } });
    fireEvent.change(screen.getByLabelText(/^Email/), { target: { value: "p@example.com" } });
    fireEvent.change(screen.getByLabelText(/Student 1: first name/), {
      target: { value: "Arjun" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Thank you. We'll be in touch soon.")).toBeInTheDocument();
    const body = calls.find((c) => c.method === "POST")?.body as {
      data: Record<string, unknown>;
      utm: Record<string, string>;
      website: string;
    };
    expect(body.data).toMatchObject({
      first_name: "Priya",
      email: "p@example.com",
      children: [{ first_name: "Arjun", subjects: "" }],
    });
    expect(body.utm.utm_source).toBe("google");
    expect(body.website).toBe("");
  });

  it("lets a family accept a waitlist place", async () => {
    window.history.pushState(null, "", "/offers/tok123");
    const offer = { student: "Arjun", subject: "Maths", details: "Tuesdays 4pm with Nia",
                    status: "offered", expires_at: "2026-10-12T10:00:00Z",
                    organisation: "Bright Minds" }; // prettier-ignore
    const calls = mockApi({
      "GET /api/v1/public/offers/tok123": { body: offer },
      "POST /api/v1/public/offers/tok123": { body: { ...offer, status: "accepted" } },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Accept the place" }));
    expect(await screen.findByText(/the place is yours/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ accept: true });
  });
});
