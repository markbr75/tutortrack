import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const COORDINATOR = {
  ...ME,
  permissions: {
    ...ME.permissions,
    "jobs.job.view": "all",
    "matching.search": "all",
    "matching.offer.manage": "all",
    "matching.posting.manage": "all",
    "matching.cover.manage": "all",
    "matching.analytics.view": "all",
  },
};

const BASE = {
  "GET /api/v1/me": { body: COORDINATOR },
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};

const factor = (score: number, value: unknown = null) => ({
  weight: 10,
  score,
  value,
  known: true,
});
const row = (rank: number, id: string, name: string, extra = {}) => ({
  rank, tutor: { id, name, headline: "", status: "active" }, score: rank === 1 ? "82.5" : "61.0",
  breakdown: { availability: factor(1, "100%"), distance: factor(0.9, 1.2) },
  distance_km: "1.2", slot_fit: [rank === 1 ? 1 : 0.5], restricted: false, reasons: [],
  point: { lat: 51.51, lng: -0.13 }, shortlisted: false, ...extra,
}); // prettier-ignore

describe("matching", () => {
  it("ranks tutors for a job and offers it to the chosen ones in order", async () => {
    window.history.pushState(null, "", "/jobs/j1/match");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/jobs/j1": {
        body: { id: "j1", name: "Arjun Maths", default_schedule: [{ weekday: 0, time: "16:00" }] },
      },
      "POST /api/v1/matching/search": {
        body: {
          query: "q1", criteria: {}, origin: { lat: 51.5, lng: -0.14 },
          results: [row(1, "t1", "Nia Okafor"), row(2, "t2", "Sam Lee")],
        },
      }, // prettier-ignore
      "GET /api/v1/job-offer-batches": { body: { results: [], next: null, previous: null } },
      "GET /api/v1/job-postings": { body: { results: [], next: null, previous: null } },
      "POST /api/v1/job-offer-batches": { status: 201, body: { id: "b1" } },
    });
    render(<App />);
    expect(await screen.findByRole("link", { name: "Nia Okafor" })).toBeInTheDocument();
    expect(screen.getByText("82.5")).toBeInTheDocument();
    expect(screen.getByText("Mon 16:00 100%")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Map of the lessons and 2 tutors" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Include restricted and unapproved tutors")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Choose Sam Lee for an offer" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Choose Nia Okafor for an offer" }));
    fireEvent.click(screen.getByRole("button", { name: "Send offers" }));
    await screen.findByText("0 tutors chosen, in the order you ticked them.");
    expect(calls.find((c) => c.method === "POST" && c.path === "/api/v1/job-offer-batches")?.body).toEqual({
      job: "j1", tutors: ["t2", "t1"], mode: "sequential", expiry_hours: 24,
    }); // prettier-ignore
  });

  it("shows the reasons for restricted tutors when they're included", async () => {
    window.history.pushState(null, "", "/jobs/j1/match");
    mockApi({
      ...BASE,
      "GET /api/v1/me": {
        body: { ...COORDINATOR, permissions: { ...COORDINATOR.permissions,
                "matching.include_restricted": "all" } },
      }, // prettier-ignore
      "GET /api/v1/jobs/j1": { body: { id: "j1", name: "Arjun Maths", default_schedule: [] } },
      "POST /api/v1/matching/search": (body) => ({
        body: {
          query: "q1", criteria: {}, origin: null,
          results: (body as { include_restricted: boolean }).include_restricted
            ? [row(1, "t3", "Kim Bell", { restricted: true, reasons: ["Subject not approved"] })]
            : [],
        },
      }), // prettier-ignore
      "GET /api/v1/job-offer-batches": { body: { results: [], next: null, previous: null } },
      "GET /api/v1/job-postings": { body: { results: [], next: null, previous: null } },
    });
    render(<App />);
    expect(await screen.findByText(/No tutors match/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Include restricted and unapproved tutors"));
    expect(await screen.findByText("Restricted")).toBeInTheDocument();
    expect(screen.getByText("Subject not approved")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Choose Kim Bell for an offer" })).toBeDisabled();
  });

  it("lists unfilled cover and assigns a free tutor", async () => {
    window.history.pushState(null, "", "/matching");
    const cover = {
      id: "c1", original_tutor: "t9", original_tutor_name: "Jo Away", reason: "", status: "open",
      deadline: "2026-10-12T14:00:00Z", notified_count: 2, accepted_by: null,
      accepted_by_name: "", accepted_at: null, closed_at: null, created_at: "2026-10-10T09:00:00Z",
      lessons: [{ id: "l1", title: "Maths with Arjun", start: "2026-10-12T16:00:00Z",
                  end: "2026-10-12T17:00:00Z", timezone: "Europe/London" }],
    }; // prettier-ignore
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/cover-requests": { body: { results: [cover], next: null, previous: null } },
      "GET /api/v1/cover-requests/c1/candidates": { body: [row(1, "t1", "Nia Okafor")] },
      "POST /api/v1/cover-requests/c1/assign": { body: { ...cover, status: "filled" } },
    });
    render(<App />);
    const item = (await screen.findByText(/Jo Away/)).closest("li") as HTMLElement;
    fireEvent.click(within(item).getByRole("button", { name: "Who's free" }));
    fireEvent.click(await screen.findByRole("button", { name: "Give them the cover" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/assign"))?.body).toEqual({ tutor: "t1" }),
    );
  });
});
