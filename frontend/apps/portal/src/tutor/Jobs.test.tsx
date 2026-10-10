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
    body: { id: "t1", name: "Nia", email: "n@x.com", can_cancel: true, can_edit_lessons: false,
            can_see_pay: true },
  }, // prettier-ignore
};

const brief = {
  subject: "Maths", level: "GCSE", students: ["Arjun P."], mode: "in_person", area: "SW1A",
  schedule: [{ weekday: 0, time: "16:00" }], start_date: "2026-10-12", pay_rate: null, notes: "",
}; // prettier-ignore

describe("tutor jobs", () => {
  it("declines an offer with a reason and applies for a job on the board", async () => {
    window.history.pushState(null, "", "/portal/tutor/jobs");
    const offer = { id: "o1", status: "sent", brief, sent_at: "2026-10-10T09:00:00Z",
                    expires_at: "2026-10-11T09:00:00Z", responded_at: null, decline_reason: "" }; // prettier-ignore
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/me/job-offers": { body: [offer] },
      "GET /api/v1/me/job-postings": {
        body: [{ id: "p1", title: "English A level", brief: { ...brief, subject: "English" },
                 published_at: "2026-10-10T09:00:00Z", closes_on: null, applied: null }],
      }, // prettier-ignore
      "GET /api/v1/me/cover-requests": { body: [] },
      "POST /api/v1/me/job-offers/o1/decline": { body: { ...offer, status: "declined" } },
      "POST /api/v1/me/job-postings/p1/apply": { status: 201, body: {} },
    });
    render(<App />);
    expect(await screen.findAllByText("Arjun P.")).toHaveLength(2);
    expect(screen.getAllByText("SW1A")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    fireEvent.change(screen.getByLabelText("Reason (optional)"), { target: { value: "Too far" } });
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    fireEvent.change(screen.getByLabelText("Message to the coordinator (optional)"), {
      target: { value: "Happy to help" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await vi.waitFor(() => {
      expect(calls.find((c) => c.path.endsWith("/decline"))?.body).toEqual({ reason: "Too far" });
      expect(calls.find((c) => c.path.endsWith("/apply"))?.body).toEqual({
        message: "Happy to help",
      });
    });
  });

  it("takes a cover request", async () => {
    window.history.pushState(null, "", "/portal/tutor/jobs");
    const cover = {
      id: "c1", original_tutor: "t9", original_tutor_name: "Jo", reason: "", status: "open",
      deadline: "2026-10-12T14:00:00Z", notified_count: 1, accepted_by: null, accepted_by_name: "",
      accepted_at: null, closed_at: null, created_at: "2026-10-10T09:00:00Z",
      lessons: [{ id: "l1", title: "Maths with Arjun", start: "2026-10-12T16:00:00Z",
                  end: "2026-10-12T17:00:00Z", timezone: "Europe/London" }],
    }; // prettier-ignore
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/me/job-offers": { body: [] },
      "GET /api/v1/me/job-postings": { body: [] },
      "GET /api/v1/me/cover-requests": { body: [cover] },
      "POST /api/v1/me/cover-requests/c1/accept": { body: { ...cover, status: "filled" } },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "I'll cover it" }));
    await vi.waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/me/cover-requests/c1/accept")).toBe(true),
    );
  });
});
