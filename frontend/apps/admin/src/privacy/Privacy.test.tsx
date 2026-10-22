import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const OWNER = {
  ...ME,
  membership: { ...ME.membership, role: "owner" },
  permissions: {
    ...ME.permissions,
    "privacy.dsar.manage": "all",
    "privacy.legal_hold.manage": "all",
    "privacy.retention.manage": "all",
    "privacy.dpa.manage": "all",
    "safeguarding.dsl": "all",
    "safeguarding.raise": "all",
    "safeguarding.lone_working.monitor": "all",
    "people.student.view": "all",
  },
};

const page = (results: unknown[]) => ({ body: { results, next: null, previous: null } });
const soon = new Date(Date.now() + 5 * 86_400_000).toISOString();

const REQUEST = {
  id: "d1", reference: "DSAR-00001", kind: "access", status: "received", channel: "email",
  subject_type: "people.student", subject_id: "s1", subject_label: "Arjun Patel",
  requester_name: "Priya Patel", requester_email: "priya@example.com", relationship: "parent",
  details: "A copy of everything", received_at: "2026-10-10T10:00:00Z", due_at: soon,
  extended_at: null, extension_reason: "",
  checklist: [
    { key: "identity", title: "Identity confirmed", is_required: true, done: false },
    { key: "matches_records", title: "Details match our records", is_required: true, done: false },
  ],
  verified_at: null, verification_note: "", summary: {}, redactions: [],
  redactions_approved_at: null, delivered_at: null, link_expires_at: null, downloaded_at: null,
  download_count: 0, erasure_approved_at: null, closed_at: null, close_reason: "",
  workflow_id: "dsar:o1:d1", has_draft: false, has_package: false,
  created_at: "2026-10-10T10:00:00Z",
}; // prettier-ignore

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: OWNER },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    ...extra,
  };
}

describe("privacy centre", () => {
  it("lists open requests with their deadline and logs a new one", async () => {
    window.history.pushState(null, "", "/privacy");
    const calls = mockApi(
      routes({
        "GET /api/v1/data-requests": page([REQUEST]),
        "GET /api/v1/search": {
          body: [
            { type: "student", id: "s1", title: "Arjun Patel", subtitle: "", score: 1, client_id: "c1" },
          ],
        }, // prettier-ignore
        "POST /api/v1/data-requests": { status: 201, body: REQUEST },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("link", { name: "DSAR-00001" })).toBeInTheDocument();
    expect(screen.getByText("due in 5 days")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Privacy" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Find the person"), { target: { value: "Arj" } });
    fireEvent.click(await screen.findByRole("button", { name: /Arjun Patel/ }));
    fireEvent.change(screen.getByLabelText("Requester's name"), {
      target: { value: "Priya Patel" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Log request and start the deadline" }));
    await vi.waitFor(() => {
      const post = calls.find((c) => c.method === "POST" && c.path === "/api/v1/data-requests");
      expect(post?.body).toMatchObject({
        subject_type: "people.student",
        subject_id: "s1",
        requester_name: "Priya Patel",
        kind: "access",
      });
    });
  });

  it("verifies identity, then reviews and redacts the export", async () => {
    window.history.pushState(null, "", "/privacy/requests/d1");
    const inReview = { ...REQUEST, status: "in_review", verified_at: "2026-10-11T10:00:00Z" };
    const calls = mockApi(
      routes({
        "GET /api/v1/data-requests/d1": { body: inReview },
        "POST /api/v1/data-requests/d1/verify": { body: inReview },
        "GET /api/v1/data-requests/d1/export-preview": {
          body: {
            sections: [
              {
                key: "crm.notes", title: "Notes", provider: "crm",
                records: [{ id: "n1", body: "About his sister" }],
              },
            ],
            files: [],
          },
        }, // prettier-ignore
        "PUT /api/v1/data-requests/d1/redactions": { body: inReview },
        "POST /api/v1/data-requests/d1/approve-export": { body: inReview },
      }),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: /DSAR-00001/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Identity confirmed" }));
    await vi.waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/data-requests/d1/verify")).toBe(true),
    );
    fireEvent.click(await screen.findByText("Notes (1)"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Leave this record out" }));
    fireEvent.click(screen.getByRole("button", { name: "Approve and send (1 item left out)" }));
    await vi.waitFor(() => {
      const put = calls.find((c) => c.method === "PUT");
      expect(put?.body).toEqual({ redactions: [{ section: "crm.notes", record_id: "n1" }] });
      expect(calls.some((c) => c.path === "/api/v1/data-requests/d1/approve-export")).toBe(true);
    });
  });

  it("names the areas of an erasure report", async () => {
    window.history.pushState(null, "", "/privacy/requests/d1");
    const erased = { ...REQUEST, kind: "erasure", status: "completed" };
    mockApi(
      routes({
        "GET /api/v1/data-requests/d1": { body: erased },
        "GET /api/v1/data-requests/d1/erasure": {
          body: {
            id: "x1", request: "d1", reason: "request", subject_type: "people.student",
            subject_id: "s1", status: "completed", subjects: {}, labels: {}, steps_done: [],
            report: {
              scheduling: { anonymised: 4, deleted: 0, retained: 0, notes: [] },
              billing: { anonymised: 1, deleted: 0, retained: 2, notes: [] },
              logins: { revoked: 1 },
            },
            area_labels: { scheduling: "Lessons", logins: "Logins ended" },
            financial_retained_until: null, financial_erased_at: null,
            completed_at: "2026-10-12T10:00:00Z", created_at: "2026-10-12T09:00:00Z",
          },
        }, // prettier-ignore
      }),
    );
    render(<App />);
    expect(await screen.findByRole("cell", { name: "Lessons" })).toBeInTheDocument();
    expect(screen.queryByRole("cell", { name: "scheduling" })).not.toBeInTheDocument();
    // An area the response doesn't name keeps its key.
    expect(screen.getByRole("cell", { name: "billing" })).toBeInTheDocument();
  });

  it("names the categories in a retention run's report", async () => {
    window.history.pushState(null, "", "/privacy");
    mockApi(
      routes({
        "GET /api/v1/data-requests": page([]),
        "GET /api/v1/retention-policies": { body: [] },
        "GET /api/v1/retention-runs": page([
          {
            id: "r1", dry_run: true, status: "completed", trigger: "manual",
            report: { "comms.messages": { due: 3, done: 0, days: 730 } },
            area_labels: { "comms.messages": "Message log and in-app notifications" },
            started_at: "2026-10-12T10:00:00Z", finished_at: "2026-10-12T10:01:00Z",
            requested_by: null, workflow_id: "",
          },
        ]), // prettier-ignore
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Retention" }));
    expect(await screen.findByText("Message log and in-app notifications: 3")).toBeInTheDocument();
  });

  it("edits retention periods and starts a dry run", async () => {
    window.history.pushState(null, "", "/privacy");
    const calls = mockApi(
      routes({
        "GET /api/v1/data-requests": page([]),
        "GET /api/v1/retention-policies": {
          body: [
            {
              id: "p1", category: "messages", category_label: "Message log", period_days: 730,
              enabled: true, updated_at: "2026-10-01T10:00:00Z",
            },
          ],
        }, // prettier-ignore
        "GET /api/v1/retention-runs": page([]),
        "PATCH /api/v1/retention-policies/p1": { body: {} },
        "POST /api/v1/retention-runs": { status: 201, body: { id: "r1" } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Retention" }));
    const days = await screen.findByLabelText("Days to keep: Message log");
    fireEvent.change(days, { target: { value: "400" } });
    fireEvent.blur(days);
    fireEvent.click(screen.getByRole("button", { name: "Report what's due (dry run)" }));
    await vi.waitFor(() => {
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ period_days: 400 });
      expect(calls.find((c) => c.path === "/api/v1/retention-runs" && c.method === "POST")?.body).toEqual({ dry_run: true }); // prettier-ignore
    });
  });
});

describe("safeguarding", () => {
  const CONCERN = {
    id: "g1", reference: "SG-00001", student: "s1", student_name: "Arjun Patel", lesson: null,
    tutor: null, category: "neglect", description: "Arrived hungry again", immediate_risk: true,
    status: "open", raised_by: "u2", raised_by_name: "Nia Adeyemi",
    raised_at: "2026-10-12T10:00:00Z", assigned_to: null, outcome: "", closed_at: null,
    attachment_ids: [], actions: [],
  }; // prettier-ignore

  it("shows cases to the safeguarding lead and records actions", async () => {
    window.history.pushState(null, "", "/safeguarding");
    const calls = mockApi(
      routes({
        "GET /api/v1/safeguarding/concerns": page([CONCERN]),
        "GET /api/v1/safeguarding/concerns/g1": { body: CONCERN },
        "GET /api/v1/safeguarding/concerns/g1/history": {
          body: [{ at: "2026-10-12T10:05:00Z", action: "read", actor: "Sam" }],
        },
        "POST /api/v1/safeguarding/concerns/g1/actions": { status: 201, body: {} },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Immediate risk")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "SG-00001" }));
    expect(await screen.findByText("Arrived hungry again")).toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Record an action" });
    fireEvent.change(within(form).getByLabelText("Note"), { target: { value: "Called mum" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add to the case" }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/actions"))?.body).toEqual({
        kind: "note",
        note: "Called mum",
      }),
    );
  });

  it("hides cases from people who are not safeguarding leads", async () => {
    window.history.pushState(null, "", "/safeguarding");
    mockApi(routes({ "GET /api/v1/me": { body: { ...ME, permissions: { "team.view": "all" } } } }));
    render(<App />);
    expect(
      await screen.findByText("Only designated safeguarding leads can see safeguarding cases."),
    ).toBeInTheDocument();
  });
});
