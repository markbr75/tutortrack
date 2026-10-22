import { createI18n, I18nextProvider } from "@tutortrack/i18n";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";
import { AiContentHelper } from "./AiParts";
import { AiEnquiryTriage, AiReplySuggest, AiThreadTools } from "./AiWidgets";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const STAFF = {
  ...ME,
  permissions: {
    ...ME.permissions,
    "ai.use": "all",
    "ai.copilot": "all",
    "ai.settings.manage": "all",
    "ai.usage.view": "all",
    "matching.search": "all",
    "comms.inbox.view": "all",
  },
};

const FEATURES = {
  lesson_report: true,
  progress_report: true,
  parent_rewrite: true,
  enquiry: true,
  inbox: true,
  command_bar: true,
  copilot: true,
  content: true,
  matching: true,
};

const STATUS = {
  available: true,
  provider: "fake",
  features: FEATURES,
  credits_exhausted: false,
  credits: {
    metered: true,
    used_this_month: 12,
    monthly_cap: null,
    balance: 1988,
    allowance: 2000,
  },
};

const PROPOSAL = {
  id: "p1",
  created_at: "2026-10-14T09:00:00Z",
  feature: "command_bar",
  action: "reschedule_lesson",
  params: {},
  summary: "Move Maths with Sam to Thu 22 Oct 2026 17:00",
  status: "proposed",
  result: {},
  error: "",
  decided_at: null,
  request: "r1",
};

function base(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: STAFF },
    "GET /api/v1/ai/status": { body: STATUS },
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

describe("command bar (FR-31-5)", () => {
  it("opens with Ctrl+J, proposes, and only changes things on confirm", async () => {
    const calls = mockApi(
      base({
        "POST /api/v1/ai/command": {
          body: {
            request: "r1",
            message: "I've proposed moving the lesson.",
            proposals: [PROPOSAL],
            searches: [],
          },
        },
        "POST /api/v1/ai/proposals/p1/confirm": {
          body: { ...PROPOSAL, status: "executed", decided_at: "2026-10-14T09:01:00Z" },
        },
      }),
    );
    render(<App />);
    await screen.findByRole("button", { name: /Ask AI/ });
    fireEvent.keyDown(window, { key: "j", ctrlKey: true });
    const dialog = await screen.findByRole("dialog", { name: "Ask AI" });
    fireEvent.change(within(dialog).getByLabelText("What would you like to do?"), {
      target: { value: "Move Sam's Thursday maths to 5pm from next week" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Go" }));
    expect(await within(dialog).findByText(PROPOSAL.summary)).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/confirm"))).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: `Confirm: ${PROPOSAL.summary}` }));
    expect(await within(dialog).findByText("Done.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/ai/command")?.body).toEqual({
      text: "Move Sam's Thursday maths to 5pm from next week",
    });
  });

  it("runs a proposed tutor search only when asked", async () => {
    const calls = mockApi(
      base({
        "POST /api/v1/ai/command": {
          body: {
            request: "r2",
            message: "",
            proposals: [],
            searches: [
              {
                subject: "s1",
                subject_name: "Chemistry",
                level: null,
                level_name: "GCSE",
                mode: "either",
                postcode: "LS6",
                weekday: "tuesday",
                after_time: "17:00",
                before_time: "21:00",
              },
            ],
          },
        },
        "POST /api/v1/matching/search": {
          body: {
            query: "q1",
            criteria: {},
            origin: null,
            results: [{ rank: 1, tutor: { id: "t1", name: "Nia Allen" }, score: "88.0" }],
          },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Ask AI/ }));
    const dialog = await screen.findByRole("dialog", { name: "Ask AI" });
    fireEvent.change(within(dialog).getByLabelText("What would you like to do?"), {
      target: { value: "Find a GCSE chemistry tutor free Tuesday evenings near LS6" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Go" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Run this search" }));
    expect(await within(dialog).findByRole("link", { name: "Nia Allen" })).toBeInTheDocument();
    const search = calls.find((c) => c.path === "/api/v1/matching/search");
    expect(search?.body).toMatchObject({
      subject: "s1",
      postcode: "LS6",
      slots: [{ weekday: 1, time: "17:00" }],
    });
  });

  it("is hidden when the organisation hasn't turned it on", async () => {
    mockApi(
      base({
        "GET /api/v1/ai/status": {
          body: { ...STATUS, features: { ...FEATURES, command_bar: false } },
        },
      }),
    );
    render(<App />);
    await screen.findByRole("navigation", { name: "Main" });
    await waitFor(() => expect(screen.queryByRole("button", { name: /Ask AI/ })).toBeNull());
  });
});

describe("copilot (FR-31-7)", () => {
  it("answers with linked report citations", async () => {
    window.history.pushState(null, "", "/copilot");
    const calls = mockApi(
      base({
        "POST /api/v1/ai/copilot": {
          body: {
            request: "r3",
            answer: "You are owed £200 over 30 days [1].",
            citations: [
              {
                index: 1,
                report: "aged_debtors",
                title: "Aged debtors",
                period: { from: "2026-10-01", to: "2026-10-14" },
                params: { period: "this_month" },
                link: "/analytics/aged_debtors?period=this_month",
              },
            ],
          },
        },
        "POST /api/v1/ai/feedback": { body: { id: "f1", rating: "up", similarity_percent: null } },
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Your question"), {
      target: { value: "What's our outstanding balance over 30 days?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    const log = await screen.findByRole("log");
    expect(await within(log).findByText(/You are owed/)).toBeInTheDocument();
    expect(within(log).getByRole("link", { name: "Open Aged debtors" })).toHaveAttribute(
      "href",
      "/analytics/aged_debtors?period=this_month",
    );
    fireEvent.click(within(log).getByRole("button", { name: "Helpful" }));
    expect(await within(log).findByText("Thanks for the feedback.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/ai/feedback")?.body).toMatchObject({
      request: "r3",
      rating: "up",
    });
  });
});

describe("AI settings (E31-T01)", () => {
  it("turns a feature on and shows usage", async () => {
    window.history.pushState(null, "", "/settings/ai");
    const rows = [
      {
        feature: "inbox",
        title: "Inbox replies, intent and summaries",
        enabled: false,
        tone: "",
        language: "",
      },
    ];
    const calls = mockApi(
      base({
        "GET /api/v1/ai/features": { body: rows },
        "PATCH /api/v1/ai/features/inbox": { body: [{ ...rows[0], enabled: true }] },
        "GET /api/v1/settings/ai": {
          body: {
            values: {
              "ai.tone": "friendly",
              "ai.spelling": "en-GB",
              "ai.monthly_credit_cap": 0,
              "ai.inbox_auto_classify": false,
            },
            schema: [],
            overrides: [],
          },
        },
        "GET /api/v1/ai/usage": {
          body: {
            period: "2026-10-01",
            totals: { requests: 3, credits: 12 },
            by_feature: [{ feature: "inbox", requests: 3, credits: 12 }],
            by_user: [],
            feedback: { up: 1 },
            credits: STATUS.credits,
          },
        },
      }),
    );
    render(<App />);
    const toggle = await screen.findByRole("checkbox", {
      name: "Turn on Inbox replies, intent and summaries",
    });
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH" && c.path.endsWith("/inbox"))?.body).toEqual({
        enabled: true,
      }),
    );
    expect(await screen.findByText(/1988 AI credits left/)).toBeInTheDocument();
  });
});

describe("drafts in existing pages", () => {
  it("suggests an inbox reply into the composer", async () => {
    const calls = mockApi(
      base({
        "POST /api/v1/ai/threads/th1/reply": { body: { request: "r4", reply: "Hi Priya, yes." } },
      }),
    );
    const onSuggest = vi.fn();
    wrap(<AiReplySuggest threadId="th1" current="" onSuggest={onSuggest} />);
    fireEvent.click(await screen.findByRole("button", { name: "Suggest reply" }));
    await waitFor(() => expect(onSuggest).toHaveBeenCalledWith("Hi Priya, yes."));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1); // nothing sent
  });

  it("summarises and shows the intent of a conversation", async () => {
    mockApi(
      base({
        "GET /api/v1/ai/thread-insights": { body: { results: [], next: null, previous: null } },
        "POST /api/v1/ai/threads/th1/summary": {
          body: {
            request: "r5",
            summary: "The family asks to move Thursday.",
            action_items: ["Reply"],
          },
        },
        "POST /api/v1/ai/threads/th1/classify": {
          body: { request: "r6", intent: "reschedule", confidence: 85, reason: "", proposal: null },
        },
      }),
    );
    wrap(<AiThreadTools threadId="th1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Summarise" }));
    expect(await screen.findByText("The family asks to move Thursday.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Classify" }));
    expect(await screen.findByText("Intent: Reschedule (85%)")).toBeInTheDocument();
  });

  it("explains a credits problem clearly", async () => {
    mockApi(
      base({
        "POST /api/v1/ai/threads/th1/reply": {
          status: 402,
          body: { type: "ai-credits-exhausted", title: "No AI credits left", status: 402 },
        },
      }),
    );
    wrap(<AiReplySuggest threadId="th1" current="" onSuggest={() => undefined} />);
    fireEvent.click(await screen.findByRole("button", { name: "Suggest reply" }));
    expect(await screen.findByText(/no AI credits left this month/)).toBeInTheDocument();
  });

  it("triages an enquiry with a proposal to confirm", async () => {
    const onApplied = vi.fn();
    mockApi(
      base({
        "POST /api/v1/ai/enquiries/e1/triage": {
          body: {
            request: "r7",
            extracted: {},
            next_steps: ["Offer a trial lesson"],
            priority: "high",
            reply_subject: "Your enquiry",
            reply_body: "Dear Priya, thank you.",
            proposal: {
              ...PROPOSAL,
              id: "p2",
              action: "update_enquiry",
              summary: "Update: priority high",
            },
          },
        },
        "POST /api/v1/ai/proposals/p2/confirm": {
          body: { ...PROPOSAL, id: "p2", status: "executed", summary: "Update: priority high" },
        },
      }),
    );
    wrap(<AiEnquiryTriage enquiryId="e1" onApplied={onApplied} />);
    fireEvent.click(await screen.findByRole("button", { name: "Triage with AI" }));
    expect(await screen.findByText("Offer a trial lesson")).toBeInTheDocument();
    expect(screen.getByText("Dear Priya, thank you.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm: Update: priority high" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalled());
  });

  it("drafts content and hands it to the editor", async () => {
    const calls = mockApi(
      base({
        "POST /api/v1/ai/content": {
          body: {
            request: "r8",
            kind: "broadcast",
            title: "",
            subject: "Half-term revision",
            body: "Hi {{ recipient.first_name }}, ...",
            meta_description: "",
            warnings: [],
          },
        },
      }),
    );
    const onUse = vi.fn();
    wrap(<AiContentHelper kind="broadcast" onUse={onUse} />);
    fireEvent.click(await screen.findByRole("button", { name: "Draft with AI" }));
    fireEvent.change(screen.getByLabelText("What should it say?"), {
      target: { value: "Half-term revision sessions" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Write draft" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use this draft" }));
    expect(onUse).toHaveBeenCalledWith(expect.objectContaining({ subject: "Half-term revision" }));
    expect(calls.find((c) => c.path === "/api/v1/ai/content")?.body).toMatchObject({
      kind: "broadcast",
      brief: "Half-term revision sessions",
    });
  });

  it("shows nothing without the ai.use permission", async () => {
    mockApi({ "GET /api/v1/me": { body: ME } });
    wrap(<AiReplySuggest threadId="th1" current="" onSuggest={() => undefined} />);
    await waitFor(() => expect(screen.queryByRole("button")).toBeNull());
  });
});
