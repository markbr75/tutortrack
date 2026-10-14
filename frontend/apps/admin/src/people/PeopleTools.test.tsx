import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

/** Gap batch G1: computed list columns, bulk actions, exports and the merge tool. */

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const PERMS = {
  ...ME.permissions,
  "people.client.view": "all",
  "people.client.edit": "all",
  "people.client.export": "all",
  "people.student.view": "all",
  "crm.bulk.run": "all",
  "comms.broadcast.send": "all",
  "people.merge": "all",
  "crm.note.view": "all",
};

const base = {
  "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};

const CLIENTS = [
  {
    id: "c1",
    display_name: "The Patel Family",
    status: "active",
    currency: "GBP",
    students_count: 2,
    balance: "120.00",
    next_lesson_at: "2026-10-20T09:00:00Z",
    last_lesson_at: "2026-10-10T09:00:00Z",
    hours_this_term: "6.50",
  },
  {
    id: "c2",
    display_name: "Patel family",
    status: "active",
    currency: "GBP",
    students_count: 1,
    balance: null,
    next_lesson_at: null,
    last_lesson_at: null,
    hours_this_term: null,
  },
];

describe("people list tools", () => {
  it("shows computed columns, sorts and exports to Excel", async () => {
    window.history.pushState(null, "", "/clients");
    const calls = mockApi({
      ...base,
      "GET /api/v1/clients": { body: { results: CLIENTS, next: null } },
    });
    render(<App />);
    await screen.findByRole("link", { name: "The Patel Family" });
    const table = screen.getByRole("table", { name: "Clients" });
    expect(within(table).getByText("£120.00")).toBeInTheDocument();
    expect(within(table).getByText("6.5 h")).toBeInTheDocument();
    expect(within(table).getByText("20 Oct 2026")).toBeInTheDocument();
    const excel = screen.getByRole("link", { name: "Export Excel" });
    expect(excel.getAttribute("href")).toContain("file_format=xlsx");
    fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: "-balance" } });
    fireEvent.click(screen.getByLabelText("Only those who owe money"));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.path === "/api/v1/clients" &&
            c.search.includes("ordering=-balance") &&
            c.search.includes("balance_min=0.01"),
        ),
      ).toBe(true),
    );
  });

  it("sends a message to the selected families in the background", async () => {
    window.history.pushState(null, "", "/clients");
    const calls = mockApi({
      ...base,
      "GET /api/v1/clients": { body: { results: CLIENTS, next: null } },
      "POST /api/v1/bulk/client/send_message": {
        status: 202,
        body: { id: "j1", status: "queued", total: 2, processed: 0, succeeded: 0, errors: {} },
      },
      "GET /api/v1/bulk-jobs/j1": {
        body: {
          id: "j1",
          status: "completed",
          total: 2,
          processed: 2,
          succeeded: 1,
          errors: { c2: "no_consent" },
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select The Patel Family" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Patel family" }));
    const bar = screen.getByRole("region", { name: "Bulk actions" });
    expect(within(bar).getByText("2 selected")).toBeInTheDocument();
    expect(within(bar).getByRole("link", { name: "Export selected (Excel)" })).toHaveAttribute(
      "href",
      "/api/v1/clients/export?ids=c1%2Cc2&file_format=xlsx",
    );
    expect(within(bar).getByRole("link", { name: "Merge the two selected" })).toHaveAttribute(
      "href",
      "/people/merge/clients/c2/c1",
    );
    fireEvent.click(within(bar).getByRole("button", { name: "Send a message" }));
    const form = screen.getByRole("form", { name: "Send a message" });
    fireEvent.change(within(form).getByLabelText("Subject"), { target: { value: "Half term" } });
    fireEvent.change(within(form).getByLabelText("Message"), { target: { value: "Hello" } });
    fireEvent.click(within(form).getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Done: 1 of 2 succeeded.")).toBeInTheDocument();
    expect(screen.getByText("no marketing consent")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      target_ids: ["c1", "c2"],
      params: { channel: "email", purpose: "service", subject: "Half term", body: "Hello" },
    });
  });
});

const PREVIEW = {
  subject_type: "people.client",
  source: { id: "c2", name: "Patel family" },
  target: { id: "c1", name: "The Patel Family" },
  values: [
    {
      name: "display_name",
      label: "Name",
      source: "Patel family",
      target: "The Patel Family",
      hidden: false,
      same: false,
      default: "target",
    },
    {
      name: "po_number",
      label: "PO number",
      source: "",
      target: "",
      hidden: false,
      same: true,
      default: "target",
    },
  ],
  moves: [
    { key: "people.students", label: "Students", count: 1 },
    { key: "billing.invoices", label: "Invoices", count: 2 },
  ],
  problems: [],
  warnings: ["The families bill in different currencies (GBP and EUR). Both balances are kept."],
  can_merge: true,
};

describe("merge tool", () => {
  it("reviews a duplicate pair, chooses values and merges after confirmation", async () => {
    window.history.pushState(null, "", "/people/duplicates");
    const calls = mockApi({
      ...base,
      "GET /api/v1/people/duplicates/pairs": {
        body: [
          {
            type: "client",
            a: {
              id: "c1",
              name: "The Patel Family",
              detail: "",
              client_id: "c1",
              created_at: "2026-01-02T10:00:00Z",
            },
            b: {
              id: "c2",
              name: "Patel family",
              detail: "",
              client_id: "c2",
              created_at: "2026-09-02T10:00:00Z",
            },
            reason: "email",
          },
        ],
      },
      "GET /api/v1/merge/clients/preview": { body: PREVIEW },
      "POST /api/v1/merge/clients": {
        body: {
          subject_type: "people.client",
          target_id: "c1",
          merged_id: "c2",
          moved: { "people.students": 1 },
          notes: ["A note on the client reminds you to merge the accounting contacts."],
        },
      },
    });
    render(<App />);
    expect(await screen.findByText("Same email")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("link", { name: "Review and merge The Patel Family and Patel family" }),
    );
    expect(await screen.findByRole("heading", { name: "Merge families" })).toBeInTheDocument();
    expect(await screen.findByText("Invoices: 2")).toBeInTheDocument();
    expect(screen.getByText(/different currencies/)).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "Merge records" });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "Use the duplicate's value for Name" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "I understand that merging can't be undone." }),
    );
    fireEvent.click(submit);
    expect(
      await screen.findByText("Merged. Everything now belongs to The Patel Family."),
    ).toBeInTheDocument();
    expect(screen.getByText(/merge the accounting contacts/)).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      source: "c2",
      target: "c1",
      choices: { display_name: "source" },
      confirm: true,
    });
  });

  it("shows why a merge is blocked", async () => {
    window.history.pushState(null, "", "/people/merge/students/s2/s1");
    mockApi({
      ...base,
      "GET /api/v1/merge/students/preview": {
        body: {
          ...PREVIEW,
          problems: ["A legal hold applies to one of these records, so they can't be merged."],
          can_merge: false,
        },
      },
    });
    render(<App />);
    expect(await screen.findByText(/legal hold/)).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "I understand that merging can't be undone." }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Merge records" })).toBeDisabled();
  });
});
