import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const COORDINATOR = {
  ...ME,
  permissions: { ...ME.permissions, "leads.enquiry.view": "all", "leads.waitlist.manage": "all" },
};

const SUGGESTION = {
  id: "ws1", entry: "w1", student: "st1", student_name: "Arjun Patel", subject: "Maths",
  level: "GCSE", position: 1, tutor: "t1", tutor_name: "Nia Okafor", reason: "availability",
  score: "78.5", status: "open", decided_at: null, created_at: "2026-10-21T09:00:00Z",
  updated_at: "2026-10-21T09:00:00Z",
}; // prettier-ignore
const ENTRY = {
  id: "w1", student: "st1", student_name: "Arjun Patel", subject: "Maths", level: "GCSE",
  tutor: null, service: null, notes: "", status: "waiting", offer_details: "",
  offered_at: null, offer_expires_at: null, responded_at: null,
  created_at: "2026-10-01T09:00:00Z", position: 1, group_class_id: null,
}; // prettier-ignore

describe("waitlist suggestions (gap G5c, FR-17-6)", () => {
  it("offers the place to a waiting student from a tutor's new capacity", async () => {
    window.history.pushState(null, "", "/leads/waitlist");
    let open = [SUGGESTION];
    const calls = mockApi({
      "GET /api/v1/me": { body: COORDINATOR },
      "GET /api/v1/organisation": { body: { status: "active" } },
      "GET /api/v1/me/organisations": { body: [] },
      "GET /api/v1/waitlist": { body: { results: [ENTRY], next: null, previous: null } },
      "GET /api/v1/waitlist-suggestions": () => ({
        body: { results: open, next: null, previous: null },
      }),
      "POST /api/v1/waitlist-suggestions/ws1/offer": () => {
        open = [];
        return { body: { ...SUGGESTION, status: "offered" } };
      },
    });
    render(<App />);
    expect(await screen.findByText("Nia Okafor has room for Arjun Patel")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "1 tutor with room" })).toBeInTheDocument();
    expect(screen.getByText(/Availability changed/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Offer details for Arjun Patel"), {
      target: { value: "Tuesdays 4pm" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Offer Arjun Patel a place with Nia Okafor" }),
    );
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/ws1/offer"))?.body).toEqual({
        details: "Tuesdays 4pm",
      }),
    );
    await vi.waitFor(() =>
      expect(screen.queryByText("Nia Okafor has room for Arjun Patel")).toBeNull(),
    );
  });

  it("dismisses a suggestion", async () => {
    window.history.pushState(null, "", "/leads/waitlist");
    const calls = mockApi({
      "GET /api/v1/me": { body: COORDINATOR },
      "GET /api/v1/organisation": { body: { status: "active" } },
      "GET /api/v1/me/organisations": { body: [] },
      "GET /api/v1/waitlist": { body: { results: [], next: null, previous: null } },
      "GET /api/v1/waitlist-suggestions": {
        body: { results: [SUGGESTION], next: null, previous: null },
      },
      "POST /api/v1/waitlist-suggestions/ws1/dismiss": {
        body: { ...SUGGESTION, status: "dismissed" },
      },
    });
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Dismiss Nia Okafor for Arjun Patel" }),
    );
    await vi.waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/dismiss"))).toBe(true),
    );
  });
});
