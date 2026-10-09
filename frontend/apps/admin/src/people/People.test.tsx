import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { textToHtml } from "../crm/html";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const PERMS = {
  ...ME.permissions,
  "people.client.view": "all",
  "people.client.create": "all",
  "people.student.view": "all",
  "people.student.edit": "all",
  "people.tutor.view": "all",
  "people.tutor.approve_subjects": "all",
  "crm.note.view": "all",
  "crm.note.view_staff_only": "all",
  "crm.note.create": "all",
  "crm.task.view": "all",
  "crm.task.create": "all",
  "crm.task.edit": "all",
  "crm.search": "all",
};

const CLIENT = {
  id: "c1",
  type: "household",
  display_name: "The Patel Family",
  status: "active",
  currency: "GBP",
  payment_terms_days: 14,
  students_count: 1,
  billing_address: { line1: "1 High St", city: "Leeds", postcode: "LS1 1AA" },
  contacts: [
    {
      id: "p1",
      full_name: "Priya Patel",
      relationship: "parent",
      email: "priya@example.com",
      is_primary: true,
      is_bill_payer: true,
    },
  ],
  students: [{ id: "s1", full_name: "Arjun Patel", year_group: "Year 10", status: "active" }],
};

const base = {
  "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};

describe("people", () => {
  it("lists clients and links to the family page", async () => {
    window.history.pushState(null, "", "/clients");
    mockApi({
      ...base,
      "GET /api/v1/clients": { body: { results: [CLIENT], next: null } },
      "GET /api/v1/clients/c1": { body: CLIENT },
      "GET /api/v1/notes": { body: { results: [], next: null } },
    });
    render(<App />);
    const link = await screen.findByRole("link", { name: "The Patel Family" });
    expect(screen.getByRole("link", { name: "Add a family" })).toBeInTheDocument();
    fireEvent.click(link);
    expect(await screen.findByRole("heading", { name: "The Patel Family" })).toBeInTheDocument();
    expect(screen.getByText("Priya Patel · Primary · Bill payer")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Arjun Patel" })).toBeInTheDocument();
    expect(await screen.findByText("No notes yet.")).toBeInTheDocument();
  });

  it("adds a note to a record", async () => {
    window.history.pushState(null, "", "/clients/c1");
    let notes: unknown[] = [];
    const calls = mockApi({
      ...base,
      "GET /api/v1/clients/c1": { body: CLIENT },
      "GET /api/v1/notes": () => ({ body: { results: notes, next: null } }),
      "POST /api/v1/notes": (body) => {
        const note = {
          id: "n1",
          ...(body as object),
          created_at: "2026-10-01T09:00:00Z",
          pinned: false,
        };
        notes = [note];
        return { status: 201, body: note };
      },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Add a note"), {
      target: { value: "Called <Mum>\n\nWants Thursdays" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));
    expect(await screen.findByText("Wants Thursdays")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      target_type: "people.client",
      target_id: "c1",
      body: "<p>Called &lt;Mum&gt;</p><p>Wants Thursdays</p>",
      visibility: "staff_only",
    });
  });

  it("creates a family in one step", async () => {
    window.history.pushState(null, "", "/clients/new");
    const calls = mockApi({
      ...base,
      "POST /api/v1/clients/quick-add": { status: 201, body: CLIENT },
      "GET /api/v1/clients/c1": { body: CLIENT },
      "GET /api/v1/notes": { body: { results: [], next: null } },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("First name"), { target: { value: "Priya" } });
    fireEvent.change(screen.getByLabelText("Last name"), { target: { value: "Patel" } });
    fireEvent.change(screen.getByLabelText("Student 1 first name"), {
      target: { value: "Arjun" },
    });
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "Maths" } });
    fireEvent.click(screen.getByRole("button", { name: "Add another student" }));
    fireEvent.change(screen.getByLabelText("Student 2 first name"), {
      target: { value: "Maya" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create family" }));
    expect(await screen.findByRole("heading", { name: "The Patel Family" })).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      contact: {
        first_name: "Priya",
        last_name: "Patel",
        email: "",
        phone: "",
        relationship: "parent",
      },
      students: [
        { first_name: "Arjun", year_group: "", subjects: [{ subject: "Maths" }] },
        { first_name: "Maya", year_group: "", subjects: [] },
      ],
    });
  });

  it("approves a tutor's subject", async () => {
    window.history.pushState(null, "", "/tutors/t1");
    let approved = false;
    const tutor = () => ({
      id: "t1",
      full_name: "Nia Okafor",
      email: "nia@example.com",
      status: "active",
      has_joined: true,
      subjects: [{ id: "ts1", subject: "Physics", level: "A level", approved }],
    });
    mockApi({
      ...base,
      "GET /api/v1/tutors/t1": () => ({ body: tutor() }),
      "POST /api/v1/tutors/t1/subjects/ts1/approve": () => {
        approved = true;
        return { body: tutor().subjects[0] };
      },
      "GET /api/v1/notes": { body: { results: [], next: null } },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve Physics" }));
    expect(await screen.findByText("Approved")).toBeInTheDocument();
  });

  it("shows my tasks and completes one", async () => {
    window.history.pushState(null, "", "/tasks");
    let status = "open";
    const calls = mockApi({
      ...base,
      "GET /api/v1/tasks": () => ({
        body: {
          results:
            status === "open"
              ? [
                  {
                    id: "k1",
                    title: "Chase invoice",
                    status,
                    due_at: "2026-01-01T09:00:00Z",
                    is_overdue: true,
                  },
                ]
              : [],
          next: null,
        },
      }),
      "PATCH /api/v1/tasks/k1": (body) => {
        status = (body as { status: string }).status;
        return { body: { id: "k1", title: "Chase invoice", status } };
      },
    });
    render(<App />);
    expect(await screen.findByText("Overdue")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: 'Mark "Chase invoice" done' }));
    expect(await screen.findByText("Nothing to do. Nice.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ status: "done" });
  });

  it("searches with ⌘K and opens a result", async () => {
    window.history.pushState(null, "", "/");
    mockApi({
      ...base,
      "GET /api/v1/search": {
        body: [
          {
            type: "student",
            id: "s1",
            title: "Arjun Patel",
            subtitle: "Year 10",
            score: 0.9,
            client_id: "c1",
          },
        ],
      },
      "GET /api/v1/students/s1": {
        body: { id: "s1", client: "c1", full_name: "Arjun Patel", status: "active", subjects: [] },
      },
      "GET /api/v1/notes": { body: { results: [], next: null } },
    });
    render(<App />);
    await screen.findByRole("button", { name: /Search/ });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const dialog = screen.getByRole("dialog", { hidden: true });
    fireEvent.change(within(dialog).getByRole("combobox", { hidden: true }), {
      target: { value: "arjun" },
    });
    const option = await within(dialog).findByRole("option", { name: /Arjun Patel/, hidden: true });
    fireEvent.click(option);
    await waitFor(() => expect(window.location.pathname).toBe("/students/s1"));
    expect(await screen.findByRole("heading", { name: "Arjun Patel" })).toBeInTheDocument();
  });
});

describe("textToHtml", () => {
  it("escapes and paragraphs plain text", () => {
    expect(textToHtml('a <b> & "c"\nline\n\n\nnext')).toBe(
      "<p>a &lt;b&gt; &amp; &quot;c&quot;<br>line</p><p>next</p>",
    );
  });
});
