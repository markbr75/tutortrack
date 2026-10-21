import { createI18n, I18nextProvider } from "@tutortrack/i18n";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { App } from "./App";
import { ProposalsSection } from "./leads/ProposalPages";
import { ShareShortlistSection } from "./matching/SharePages";
import { ME, mockApi } from "./test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

function signedIn(permissions: Record<string, string>, extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: { ...ME.permissions, ...permissions } } },
    "GET /api/v1/organisation": { body: { status: "active" } },
    "GET /api/v1/me/organisations": { body: [] },
    ...extra,
  };
}

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={createI18n("en-GB")}>
      <QueryClientProvider client={client}>{node}</QueryClientProvider>
    </I18nextProvider>,
  );
}

const CARD = {
  id: "t1",
  name: "Nia A.",
  headline: "Maths specialist",
  bio: "Patient and clear.",
  photo_url: "",
  subjects: [{ subject: "Maths", level: "GCSE" }],
  qualifications: [{ title: "BSc Mathematics", institution: "", year: 2015 }],
  years_experience: 6,
  languages: ["English"],
  online: true,
  in_person: true,
  rating: 4.8,
  rating_count: 12,
};

describe("people map (E05-T12)", () => {
  it("plots people with labelled markers, lists them and geocodes the missing", async () => {
    window.history.pushState(null, "", "/people/map");
    const calls = mockApi(
      signedIn(
        { "people.student.view": "all", "people.student.edit": "all" },
        {
          "GET /api/v1/people/map": {
            body: {
              points: [
                {
                  kind: "student", id: "s1", name: "Arjun Patel", status: "active", area: "SW11",
                  lat: 51.464, lng: -0.163, subjects: ["Maths"], travel_radius_km: null,
                },
                {
                  kind: "tutor", id: "t1", name: "Nia Clarke", status: "active", area: "SW4",
                  lat: 51.462, lng: -0.138, subjects: ["Maths"], travel_radius_km: 5,
                },
              ], // prettier-ignore
              missing: { student: 2, tutor: 0 },
            },
          },
          "POST /api/v1/people/map/geocode": { body: { queued: 2 } },
        },
      ),
    );
    render(<App />);
    const marker = await screen.findByRole("button", { name: "Student: Arjun Patel, SW11" });
    fireEvent.keyDown(marker, { key: "Enter" });
    expect(await screen.findByRole("link", { name: "Open record" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tutor: Nia Clarke, SW4" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "List" }));
    expect(screen.getByRole("table", { name: "Students and tutors by area" })).toBeInTheDocument();
    expect(screen.getByText("5 km")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Find their map positions" }));
    expect(await screen.findByText(/Looking up 2 addresses/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/people/map/geocode")?.body).toEqual({
      kinds: ["student", "tutor"],
    });
  }, 15_000); // renders the full map; can pass 5 s on a loaded machine
});

describe("lesson feedback (E09-T09)", () => {
  it("lets a family rate the lesson from the link", async () => {
    window.history.pushState(null, "", "/feedback/tok123");
    const shown = {
      organisation: "Bright Minds", student: "Arjun", tutor: "Nia", lesson: "GCSE Maths",
      lesson_date: "2026-10-13", status: "sent", expires_at: "2026-10-20T10:00:00Z", rating: null,
    }; // prettier-ignore
    const calls = mockApi({
      "GET /api/v1/public/lesson-feedback/tok123": { body: shown },
      "POST /api/v1/public/lesson-feedback/tok123": {
        body: { ...shown, status: "answered", rating: 4 },
      },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "How was Arjun's lesson?" })).toBeVisible();
    fireEvent.click(screen.getByLabelText("4 stars"));
    fireEvent.change(screen.getByLabelText("Anything you'd like to tell us? (optional)"), {
      target: { value: "Lovely" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send feedback" }));
    expect(await screen.findByText("Thank you for your feedback.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      rating: 4,
      comment: "Lovely",
      stop_asking: false,
    });
  });

  it("shows staff the answers and a summary per tutor", async () => {
    window.history.pushState(null, "", "/lesson-feedback");
    const row = {
      id: "f1", lesson: "l1", lesson_title: "GCSE Maths", lesson_start: "2026-10-13T16:00:00Z",
      lesson_date: "2026-10-13", student: { id: "s1", name: "Arjun Patel" },
      tutor: { id: "t1", name: "Nia Clarke" }, contact_name: "Priya", status: "sent",
      skip_reason: "", sent_at: "2026-10-13T18:00:00Z", expires_at: "2026-10-20T18:00:00Z",
      rating: null, comment: "", answered_at: null, low_score_alerted: false,
    }; // prettier-ignore
    const calls = mockApi(
      signedIn(
        { "delivery.feedback.view": "all", "delivery.feedback.manage": "all" },
        {
          "GET /api/v1/lesson-feedback": { body: { results: [row], next: null, previous: null } },
          "GET /api/v1/lesson-feedback/summary": {
            body: {
              asked: 4, answered: 3, answer_rate: "75.0", average: "4.7",
              stars: { "1": 0, "2": 0, "3": 0, "4": 1, "5": 2 },
              tutors: [{ tutor_id: "t1", tutor: "Nia Clarke", average: "4.7", answered: 3, asked: 4 }],
            }, // prettier-ignore
          },
          "POST /api/v1/lesson-feedback/f1/withdraw": { body: { ...row, status: "expired" } },
        },
      ),
    );
    render(<App />);
    expect(await screen.findByText("75.0%")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "By tutor" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Withdraw the request for Arjun Patel" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/lesson-feedback/f1/withdraw")).toBe(true),
    );
  });
});

describe("proposals (E17-T09)", () => {
  it("lets the family choose a tutor and accept by typing their name", async () => {
    window.history.pushState(null, "", "/proposals/ptok");
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const proposal = {
      organisation: "Bright Minds", number: "PRO-000001", title: "GCSE Maths for Arjun",
      status: "sent", introduction: "Thank you for talking to us.", schedule: "Tuesdays 16:00",
      terms: "", lines: [{ description: "GCSE Maths 1:1", quantity: "12", unit_price: "45.00", amount: "540.00" }],
      currency: "GBP", total: "540.00", deposit: "90.00", expires_at: "2026-10-28T10:00:00Z",
      tutors: [CARD, { ...CARD, id: "t2", name: "Sam O." }], chosen_tutor: null,
      students: ["Arjun"], pay_url: "",
    }; // prettier-ignore
    const calls = mockApi({
      "GET /api/v1/public/proposals/ptok": { body: proposal },
      "POST /api/v1/public/proposals/ptok": {
        body: { ...proposal, status: "accepted", chosen_tutor: "t2", pay_url: "/pay/abc" },
      },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "GCSE Maths for Arjun" })).toBeVisible();
    expect(screen.getAllByText("£540.00", { selector: "td" })).toHaveLength(2);
    fireEvent.click(screen.getByLabelText("Choose Sam O."));
    fireEvent.change(screen.getByLabelText("Type your full name to accept"), {
      target: { value: "Priya Patel" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Accept and pay the deposit" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/pay/abc"));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      name: "Priya Patel",
      tutor: "t2",
    });
  });

  it("drafts and sends a proposal from the enquiry", async () => {
    const draft = {
      id: "p1", enquiry: "e1", number: "PRO-000001", title: "GCSE Maths", contact: "c1",
      contact_name: "Priya", status: "draft", state: "draft", introduction: "", schedule: "",
      terms: "", lines: [{ service: null, description: "Lesson", quantity: "10", unit_price: "40.00", amount: "400.00" }],
      tutors: [], currency: "GBP", total: { amount: "400.00", currency: "GBP" }, deposit: null,
      valid_days: 14, sent_at: null, expires_at: null, viewed_at: null, responded_at: null,
      accepted_name: "", chosen_tutor: null, chosen_tutor_name: "", decline_reason: "",
      payment_request: null, job_ids: [], link: "", created_at: "2026-10-14T09:00:00Z",
    }; // prettier-ignore
    let list = [] as unknown[];
    const calls = mockApi(
      signedIn(
        { "leads.proposal.manage": "all" },
        {
          "GET /api/v1/proposals": () => ({ body: { results: list, next: null, previous: null } }),
          "GET /api/v1/catalogue/services": { body: [] },
          "GET /api/v1/tutors": { body: { results: [], next: null, previous: null } },
          "POST /api/v1/proposals": () => {
            list = [draft];
            return { status: 201, body: draft };
          },
          "POST /api/v1/proposals/p1/send": () => {
            list = [{ ...draft, status: "sent", state: "sent", link: "https://x/proposals/t" }];
            return { body: list[0] };
          },
        },
      ),
    );
    window.history.pushState(null, "", "/");
    wrap(<ProposalsSection enquiryId="e1" />);
    // /me is needed for permissions: wait for it before acting.
    fireEvent.click(await screen.findByRole("button", { name: "New proposal" }));
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Lesson" } });
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Price each"), { target: { value: "40.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    fireEvent.click(await screen.findByRole("button", { name: "Send" }));
    expect(await screen.findByRole("link", { name: "Family's link" })).toBeInTheDocument();
    const created = calls.find((c) => c.method === "POST" && c.path === "/api/v1/proposals");
    expect(created?.body).toMatchObject({
      enquiry: "e1",
      lines: [{ service: null, description: "Lesson", quantity: "10", unit_price: "40.00" }],
      deposit: null,
    });
  });
});

describe("shortlist sharing (E19-T08)", () => {
  it("lets the family pick a tutor from the shared shortlist", async () => {
    window.history.pushState(null, "", "/shortlists/stok");
    const page = {
      organisation: "Bright Minds", status: "active", expires_at: "2026-10-28T10:00:00Z",
      message: "Three tutors we think would suit Arjun.",
      job: { subject: "Maths", level: "GCSE", service: "Maths 1:1", students: ["Arjun"], online: false },
      tutors: [CARD], chosen_tutor: null,
    }; // prettier-ignore
    const calls = mockApi({
      "GET /api/v1/public/shortlists/stok": { body: page },
      "POST /api/v1/public/shortlists/stok": {
        body: { ...page, status: "chosen", chosen_tutor: "t1" },
      },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Tutors for Maths GCSE" })).toBeVisible();
    expect(screen.getByText("Rated 4.8 out of 5 (12 ratings)")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Choose Nia A."));
    fireEvent.change(screen.getByLabelText("Anything we should know? (optional)"), {
      target: { value: "Tuesdays please" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Choose this tutor" }));
    expect(await screen.findByText(/Thank you for choosing/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      tutor: "t1",
      note: "Tuesdays please",
    });
  });

  it("shares the shortlist and shows what the family did", async () => {
    const share = {
      id: "sh1", job: "j1", tutors: ["t1"], contact: "c1", contact_name: "Priya Patel",
      message: "", status: "chosen", state: "chosen", expires_at: "2026-10-28T10:00:00Z",
      viewed_at: "2026-10-14T10:00:00Z", chosen_tutor: "t1", chosen_tutor_name: "Nia Clarke",
      chosen_at: "2026-10-14T11:00:00Z", client_note: "Tuesdays please", offer_batch: null,
      link: "", created_at: "2026-10-14T09:00:00Z",
    }; // prettier-ignore
    const calls = mockApi(
      signedIn(
        { "matching.shortlist.share": "all" },
        {
          "GET /api/v1/shortlists": {
            body: [{ id: "s1", job: "j1", tutor: "t1", tutor_name: "Nia Clarke", score: "80.0", breakdown: {}, note: "", created_at: "2026-10-14T09:00:00Z" }],
          }, // prettier-ignore
          "GET /api/v1/shortlist-shares": {
            body: { results: [share], next: null, previous: null },
          },
          "POST /api/v1/shortlist-shares": { status: 201, body: share },
        },
      ),
    );
    wrap(<ShareShortlistSection jobId="j1" />);
    expect(await screen.findByText(/Chose Nia Clarke/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Send to the family" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        job: "j1",
        message: "",
        days: 14,
      }),
    );
  });
});

describe("custom report builder (E26-T08)", () => {
  it("builds, runs and saves a report from whitelisted columns", async () => {
    window.history.pushState(null, "", "/analytics/builder");
    const dataset = {
      key: "charges", label: "Charges", description: "", category: "finance",
      category_label: "Finance", date_field: "date",
      dimensions: [
        { key: "date", label: "Date", type: "date", grains: ["day", "month"], choices: [], operators: ["eq", "gte", "lte"] },
        { key: "kind", label: "Type", type: "text", grains: [], choices: [], operators: ["eq", "in"] },
      ],
      measures: [
        { key: "count", label: "Rows", type: "count" },
        { key: "gross", label: "Gross", type: "money" },
      ],
    }; // prettier-ignore
    const calls = mockApi(
      signedIn(
        {
          "reporting.builder.use": "all",
          "reporting.finance.view": "all",
          "reporting.dashboard.view": "all",
        },
        {
          "GET /api/v1/reporting/builder/datasets": { body: [dataset] },
          "GET /api/v1/custom-reports": { body: { results: [], next: null, previous: null } },
          "POST /api/v1/reporting/builder/run": {
            body: {
              definition: {}, period: { from: "2026-10-01", to: "2026-10-31" },
              columns: [
                { key: "kind", label: "Type", type: "text" },
                { key: "currency", label: "Currency", type: "text" },
                { key: "gross", label: "Gross", type: "money" },
              ],
              rows: [{ kind: "lesson", currency: "GBP", gross: "70.00" }],
              totals: [{ currency: "GBP", gross: "70.00" }],
              chart: null, notes: [], truncated: false, generated_at: "2026-10-14T10:00:00Z",
            },
          }, // prettier-ignore
          "POST /api/v1/custom-reports": {
            status: 201,
            body: {
              id: "r1", name: "By type", description: "", dataset: "charges", definition: {},
              shared: true, owner_name: "Sam", is_mine: true,
              created_at: "2026-10-14T10:00:00Z", updated_at: "2026-10-14T10:00:00Z",
            },
          }, // prettier-ignore
        },
      ),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Custom report builder" })).toBeVisible();
    fireEvent.change(await screen.findByLabelText("Column"), { target: { value: "kind" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByLabelText("Gross"));
    fireEvent.click(screen.getByRole("button", { name: "Add a filter" }));
    const filter = screen.getByRole("group", { name: "Filter 1" });
    fireEvent.change(filter.querySelector("select")!, { target: { value: "kind" } });
    fireEvent.change(screen.getAllByLabelText("Value")[0]!, { target: { value: "lesson" } });
    fireEvent.click(screen.getByRole("button", { name: "Run report" }));
    expect(await screen.findByText("£70.00", { selector: "tbody td" })).toBeInTheDocument();
    const run = calls.find((c) => c.path === "/api/v1/reporting/builder/run");
    expect(run?.body).toMatchObject({
      dataset: "charges",
      group_by: ["kind"],
      measures: ["count", "gross"],
      filters: [{ field: "kind", op: "eq", value: "lesson" }],
    });
    fireEvent.change(screen.getByLabelText("Report name"), { target: { value: "By type" } });
    fireEvent.click(screen.getByLabelText("Share with colleagues who can see this data"));
    fireEvent.click(screen.getByRole("button", { name: "Save report" }));
    expect(await screen.findByText("Report saved.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/custom-reports" && c.method === "POST")?.body)
      .toMatchObject({ name: "By type", shared: true }); // prettier-ignore
  });
});
