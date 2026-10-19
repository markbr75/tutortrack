import { render, screen, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";
import { subtractAmounts } from "./data";

const ORG = {
  id: "o1",
  name: "Bright Minds",
  slug: "brightminds",
  status: "active",
  timezone: "Europe/London",
  default_currency: "GBP",
};

function lesson(id: string, title: string, start: string, end: string, status: string) {
  return {
    id,
    title,
    start,
    end,
    status,
    online: false,
    location: "Hampstead room 2",
    tutors: [{ id: `t-${id}`, tutor: "nia", name: "Nia Adeyemi" }],
    attendees: [{ id: `a-${id}`, student: "s1", name: "Maya Patel" }],
  };
}

const PERMISSIONS = {
  "scheduling.lesson.view": "all",
  "scheduling.lesson.complete": "all",
  "scheduling.lesson.create": "all",
  "billing.invoice.view": "all",
  "people.client.create": "all",
  "reporting.finance.view": "all",
  "reporting.payroll.view": "all",
};

function routes(permissions: Record<string, string> = PERMISSIONS) {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions } },
    "GET /api/v1/organisation": { body: ORG },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/lessons": {
      body: {
        next: null,
        previous: null,
        results: [
          lesson(
            "l1",
            "A-level Chemistry",
            "2026-10-19T08:00:00Z",
            "2026-10-19T09:00:00Z",
            "completed",
          ),
          lesson("l2", "KS3 English", "2026-10-19T12:30:00Z", "2026-10-19T13:30:00Z", "missed"),
          lesson("l3", "Year 4 Maths", "2026-10-19T13:00:00Z", "2026-10-19T14:00:00Z", "planned"),
          lesson(
            "l4",
            "GCSE Higher Maths",
            "2026-10-19T15:30:00Z",
            "2026-10-19T16:30:00Z",
            "planned",
          ),
        ],
      },
    },
    "GET /api/v1/unconfirmed-lessons": {
      body: [
        lesson("u1", "Year 6 11+ Prep", "2026-10-10T09:00:00Z", "2026-10-10T10:00:00Z", "planned"),
      ],
    },
    "GET /api/v1/invoices": {
      body: {
        next: null,
        previous: null,
        results: [
          {
            id: "i1",
            number: "INV-0142",
            client_name: "The Okafor Family",
            due_date: "2026-10-02",
            balance_due: { amount: "240.00", currency: "GBP" },
          },
        ],
      },
    },
    "GET /api/v1/reporting/widgets/revenue": {
      body: { values: [{ label: "", currency: "GBP", value: "6820.00", previous: "6110.00" }] },
    },
    "GET /api/v1/reporting/widgets/outstanding": {
      body: {
        values: [
          { label: "Outstanding", currency: "GBP", value: "1240.00", previous: null },
          { label: "Overdue", currency: "GBP", value: "380.00", previous: null },
        ],
      },
    },
    "GET /api/v1/reporting/widgets/next_pay_run": {
      body: { values: [{ label: "", currency: "GBP", value: "3905.40", previous: null }] },
    },
    "GET /api/v1/features": { body: {} },
    "GET /api/v1/setup-checklist": { body: { dismissed_at: "2026-10-01T00:00:00Z", steps: [] } },
  };
}

describe("home", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-19T14:12:00Z")); // 15:12 in London
  });
  afterEach(() => vi.useRealTimers());

  it("greets by name and summarises the day", async () => {
    mockApi(routes());
    render(<App />);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Good afternoon, Sam" }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/4 lessons today/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add a family" })).toHaveAttribute(
      "href",
      "/clients/new",
    );
    expect(screen.getByRole("button", { name: "Book a lesson" })).toBeInTheDocument();
  });

  it("shows today's register with a mark per lesson and the rule at now", async () => {
    mockApi(routes());
    render(<App />);
    const register = await screen.findByRole("region", { name: "Today's register" });
    expect(await within(register).findByText("A-level Chemistry")).toBeInTheDocument();
    expect(within(register).getByText("Marked 2 of 4")).toBeInTheDocument();
    expect(within(register).getByRole("img", { name: "Completed" })).toBeInTheDocument();
    expect(within(register).getByRole("img", { name: "Missed" })).toBeInTheDocument();
    // Year 4 Maths ended at 15:00 and is still planned: over, not marked.
    expect(within(register).getByRole("img", { name: "Not marked yet" })).toBeInTheDocument();
    expect(within(register).getByRole("img", { name: "Still to come" })).toBeInTheDocument();
    // The rule is decoration for sighted users (aria-hidden), so read the table rows directly.
    const rows = [...register.querySelectorAll("tbody tr")];
    const nowRow = rows.findIndex((row) => /Now · 15:12/.test(row.textContent ?? ""));
    const upcoming = rows.findIndex((row) => /GCSE Higher Maths/.test(row.textContent ?? ""));
    expect(nowRow).toBeGreaterThan(0);
    expect(nowRow).toBe(upcoming - 1);
  });

  it("lists what needs marking and the overdue invoices", async () => {
    mockApi(routes());
    render(<App />);
    const marking = await screen.findByRole("region", { name: "Needs marking" });
    expect(await within(marking).findByText(/Year 6 11\+ Prep/)).toBeInTheDocument();
    expect(within(marking).getByText("9 days")).toBeInTheDocument();
    expect(within(marking).getByRole("link", { name: "Open unconfirmed lessons" })).toHaveAttribute(
      "href",
      "/unconfirmed",
    );
    const overdue = screen.getByRole("region", { name: "Overdue invoices" });
    expect(await within(overdue).findByText("The Okafor Family")).toBeInTheDocument();
    expect(within(overdue).getByText("£240.00")).toBeInTheDocument();
  });

  it("puts this month's money on one line, the change said in words", async () => {
    mockApi(routes());
    render(<App />);
    const money = await screen.findByRole("region", { name: "Money this month" });
    expect(await within(money).findByText("£6,820.00")).toBeInTheDocument();
    expect(within(money).getByText("Up £710.00 on last month")).toBeInTheDocument();
    expect(within(money).getByText("£1,240.00")).toBeInTheDocument();
    expect(within(money).getByText("£380.00 overdue")).toBeInTheDocument();
    expect(within(money).getByText("£3,905.40")).toBeInTheDocument();
  });

  it("shows only what the role may see", async () => {
    mockApi(routes({ "scheduling.lesson.view": "all" }));
    render(<App />);
    expect(await screen.findByRole("region", { name: "Today's register" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Money this month" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Needs marking" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Overdue invoices" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Book a lesson" })).not.toBeInTheDocument();
  });
});

describe("subtractAmounts", () => {
  it.each([
    ["6820.00", "6110.00", "710.00"],
    ["6110.00", "6820.00", "-710.00"],
    ["0.10", "0.20", "-0.10"],
    ["100", "0.5", "99.5"],
    ["1000", "1000", "0"],
    ["1.005", "0.004", "1.001"],
  ])("%s − %s = %s", (a, b, diff) => {
    expect(subtractAmounts(a, b)).toBe(diff);
  });
});
