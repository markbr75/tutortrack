import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const OWNER = {
  ...ME,
  permissions: {
    ...ME.permissions,
    "automation.view": "all",
    "automation.manage": "all",
    "automation.builtin.manage": "all",
  },
};
const BASE = {
  "GET /api/v1/me": { body: OWNER },
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};

const SCHEMA = {
  record_types: [
    {
      key: "branch", label: "Branch", recipients: [], taggable: false, date_fields: [],
      stop_when: [], start_dates: [],
    },
    {
      key: "invoice", label: "Invoice", recipients: ["client", "owner"], taggable: true,
      date_fields: [{ path: "invoice.due_date", label: "Due", type: "date" }],
      stop_when: ["invoice.paid", "invoice.voided"],
      start_dates: [{ field: "due_date", label: "Due", type: "date" }],
    },
    {
      key: "lesson", label: "Lesson", recipients: ["client", "tutor"], taggable: true,
      date_fields: [{ path: "lesson.start", label: "Start", type: "datetime" }],
      stop_when: ["lesson.cancelled"],
      start_dates: [{ field: "start", label: "Start", type: "datetime" }],
    },
  ],
  starts: {
    events: [
      { event: "invoice.issued", label: "Invoice issued", subject: "invoice" },
      { event: "invoice.paid", label: "Invoice paid", subject: "invoice" },
      { event: "invoice.voided", label: "Invoice voided", subject: "invoice" },
      { event: "lesson.cancelled", label: "Lesson cancelled", subject: "lesson" },
    ],
    dates: [], schedules: [], frequencies: ["daily", "weekly", "monthly"],
  },
  questions: [
    { key: "invoice.unpaid", label: "The invoice is still unpaid", subject: "invoice" },
    { key: "invoice.auto_pay", label: "The family pays automatically", subject: "invoice" },
    { key: "lesson.still_planned", label: "The lesson is still going ahead", subject: "lesson" },
  ],
  actions: [
    { key: "send_invoice_reminder", label: "Send a payment reminder", subjects: ["invoice"],
      permission: "", allowed: true, fields: [], message: "invoice_reminder" },
    { key: "collect_payment", label: "Collect payment now", subjects: ["invoice"],
      permission: "payments.payment.record", allowed: true, fields: [], message: "" },
    { key: "send_lesson_reminder", label: "Send lesson reminder", subjects: ["lesson"],
      permission: "", allowed: true, fields: [], message: "lesson_reminder" },
    { key: "start_invoice_run", label: "Start an invoice run", subjects: ["branch"],
      permission: "billing.invoice.create", allowed: true, message: "",
      fields: [{ name: "period", label: "Period", type: "choice", required: true,
                 choices: ["schedule", "last_month"] }] },
    { key: "send_message", label: "Send a message", subjects: [], permission: "", allowed: true,
      message: "", fields: [
        { name: "to", label: "To", type: "multi", required: true, choices: ["client"] },
        { name: "channels", label: "Channels", type: "multi", required: true, choices: ["email"] },
        { name: "body", label: "Message", type: "template", required: true, choices: [] },
      ] },
    { key: "send_saved_reply", label: "Send a saved message", subjects: [], permission: "",
      allowed: true, message: "", fields: [
        { name: "template", label: "Saved message", type: "saved_reply", required: true,
          choices: [] },
      ] },
  ],
}; // prettier-ignore
const FIELDS = { subjects: [], triggers: [], actions: [], operators: [], predicates: {} };

const BUILTIN = {
  description: "", conditions: {}, stop_when: [], version: 1, enabled: true, paused: false,
  max_runs_per_record: 1, recipe_key: "", kind: "builtin", builtin_version: 1, edited: false,
  runs_under_way: 0, created_at: "2026-10-10T09:00:00Z", updated_at: "2026-10-10T09:00:00Z",
}; // prettier-ignore
const INVOICING = {
  ...BUILTIN, id: "w1", name: "Invoicing cycle", builtin_key: "invoicing_cycle",
  trigger_type: "schedule", subject_type: "branch",
  trigger_config: { subject: "branch", frequency: "monthly", day: 1, time: "06:00",
                    start: "invoice_run.due" },
  steps: [{ type: "action", action: "start_invoice_run",
            config: { period: "schedule", review_days: 2, issue: "after_review", email: true } }],
  builtin: { group: "invoicing", group_label: "Invoicing and payment chasing", latest_version: 1,
             update_available: false, can_switch_off: true, off_means: "" },
}; // prettier-ignore
const CHASING = {
  ...BUILTIN, id: "w2", name: "Payment chasing", builtin_key: "payment_chasing",
  trigger_type: "event", subject_type: "invoice", trigger_config: { event: "invoice.issued" },
  stop_when: ["invoice.paid"], edited: true, runs_under_way: 3,
  steps: [
    { type: "wait", until: "invoice.due_date", offset_days: -3, at: "09:00" },
    { type: "action", action: "send_invoice_reminder", config: {} },
    { type: "wait", until: "invoice.due_date", offset_days: 7, at: "09:00" },
    { type: "action", action: "send_invoice_reminder", config: {} },
  ],
  builtin: { group: "invoicing", group_label: "Invoicing and payment chasing", latest_version: 2,
             update_available: true, can_switch_off: false, off_means: "" },
}; // prettier-ignore
const REMINDERS = {
  ...BUILTIN, id: "w3", name: "Lesson reminders", builtin_key: "lesson_reminders",
  trigger_type: "date", subject_type: "lesson", enabled: false,
  trigger_config: { subject: "lesson", field: "start", minutes: [-1440, -120] },
  conditions: { predicate: "lesson.still_planned" },
  steps: [{ type: "action", action: "send_lesson_reminder", config: {} }],
  builtin: { group: "lessons", group_label: "Lesson communications", latest_version: 1,
             update_available: false, can_switch_off: true, off_means: "" },
}; // prettier-ignore

function editor(workflow: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  const id = String(workflow.id);
  window.history.pushState(null, "", `/workflows/${id}`);
  return mockApi({
    ...BASE,
    "GET /api/v1/workflow-schema": { body: SCHEMA },
    "GET /api/v1/automation-schema": { body: FIELDS },
    [`GET /api/v1/workflows/${id}`]: { body: workflow },
    [`GET /api/v1/workflows/${id}/runs`]: { body: [] },
    [`PUT /api/v1/workflows/${id}`]: (body: unknown) => ({
      body: { ...workflow, ...(body as object), version: Number(workflow.version) + 1 },
    }),
    ...extra,
  });
}

const putBody = (calls: ReturnType<typeof mockApi>) =>
  calls.find((c) => c.method === "PUT")?.body as Record<string, unknown> | undefined;

describe("the workflows list", () => {
  it("groups the built-ins, switches them and lists templates and runs", async () => {
    window.history.pushState(null, "", "/automations"); // the old address still works
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/workflow-schema": { body: SCHEMA },
      "GET /api/v1/automation-schema": { body: FIELDS },
      "GET /api/v1/workflows": { body: [INVOICING, CHASING, REMINDERS] },
      "POST /api/v1/workflows/w3/enable": { body: { ...REMINDERS, enabled: true } },
      "GET /api/v1/automation-recipes": {
        body: [{ key: "birthdays", name: "Birthday messages", description: "x",
                 trigger_type: "date", trigger_config: {}, installed: false }],
      }, // prettier-ignore
      "POST /api/v1/automation-recipes/birthdays/install": { status: 201, body: INVOICING },
      "GET /api/v1/workflow-runs": {
        body: { results: [{ id: "r1", automation: "w2", automation_name: "Payment chasing",
                            version: 2, subject_type: "invoice", subject_id: "i1234567890",
                            event_type: "", status: "failed", started_at: "2026-10-10T09:00:00Z",
                            finished_at: null, causation_depth: 0, attempts: 1,
                            error: "The card was declined" }], next: null, previous: null },
      }, // prettier-ignore
      "POST /api/v1/workflow-runs/r1/retry": { body: {} },
    });
    render(<App />);
    const invoicing = await screen.findByRole("region", { name: "Invoicing and payment chasing" });
    expect(within(invoicing).getByRole("link", { name: "Payment chasing" })).toBeInTheDocument();
    expect(
      within(invoicing).getByText(/Changed from the default · Newer default/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Payment chasing switched on")).toBeDisabled(); // can't switch off
    fireEvent.click(screen.getByLabelText("Lesson reminders switched on"));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/w3/enable"))).toBe(true));

    fireEvent.click(screen.getByRole("tab", { name: "Your workflows" }));
    expect(await screen.findByText(/No workflows of your own yet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Templates" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use template" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/install"))).toBe(true));
    fireEvent.click(screen.getByRole("tab", { name: "Runs" }));
    const row = (await screen.findByText("The card was declined")).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Retry from the failed step" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/r1/retry"))).toBe(true));
  });
});

describe("the sequence editor", () => {
  it("changes when invoices go out in a few clicks (the usability check)", async () => {
    const calls = editor(INVOICING);
    render(<App />);
    const start = await screen.findByRole("region", { name: "Start" });
    expect(
      within(start).getByText("Every month on day 1 at 06:00, for each branch"),
    ).toBeInTheDocument();
    // 1. Edit the start  2. pick the 5th  3. Save.
    fireEvent.click(within(start).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(start).getByLabelText("Day of the month"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(putBody(calls)).toBeDefined());
    const body = putBody(calls);
    expect(body?.trigger_config).toEqual({ ...INVOICING.trigger_config, day: 5 });
    expect(body?.steps).toEqual(INVOICING.steps); // nothing else changes
    expect(await screen.findByText("Saved. New runs use these steps.")).toBeInTheDocument();
  });

  it("reads as sentences and changes a step in place", async () => {
    const calls = editor(CHASING);
    render(<App />);
    const start = await screen.findByRole("region", { name: "Start" });
    expect(within(start).getByText("When this happens: Invoice issued")).toBeInTheDocument();
    expect(within(start).getByText("Invoice paid")).toBeInTheDocument();
    const first = screen.getByRole("region", { name: "Step 1" });
    expect(within(first).getByText("3 days before “Due”, at 09:00")).toBeInTheDocument();
    expect(within(first).getByText("Send a payment reminder")).toBeInTheDocument();
    expect(screen.getByText(/TutorTrack has improved this workflow/)).toBeInTheDocument();
    // The second reminder: 14 days after the due date, and only if still unpaid.
    const second = screen.getByRole("region", { name: "Step 2" });
    fireEvent.click(within(second).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(second).getByLabelText("How many"), { target: { value: "14" } });
    fireEvent.change(within(second).getByLabelText("Only if"), {
      target: { value: "invoice.unpaid" },
    });
    expect(within(second).getByRole("link", { name: "Edit wording" })).toHaveAttribute(
      "href",
      "/settings/notifications?edit=invoice_reminder",
    );
    expect(screen.getByText(/3 runs are under way/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(putBody(calls)).toBeDefined());
    expect(putBody(calls)?.steps).toEqual([
      CHASING.steps[0],
      CHASING.steps[1],
      { type: "wait", until: "invoice.due_date", offset_days: 14, at: "09:00" },
      { ...CHASING.steps[3], only_if: { predicate: "invoice.unpaid" } },
    ]);
    expect(putBody(calls)?.stop_when).toEqual(["invoice.paid"]);
  });

  it("adds a split, moves and deletes steps, and won't save until each card is complete", async () => {
    const calls = editor(CHASING);
    render(<App />);
    await screen.findByRole("region", { name: "Step 2" });
    fireEvent.click(
      screen.getAllByRole("button", { name: "Add a Yes / No split" }).at(-1) as HTMLElement,
    );
    const split = screen.getByRole("region", { name: "Step 3: Yes / No" });
    expect(within(split).getByText("Choose the question", { selector: "li" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByText("Fix 2 problems before saving.")).toBeInTheDocument();
    fireEvent.change(within(split).getByLabelText("Question"), {
      target: { value: "invoice.auto_pay" },
    });
    const yes = screen.getByRole("list", { name: "Steps if the answer is yes" });
    const yesCard = within(yes).getByRole("region", { name: "Yes: step 1" });
    fireEvent.click(within(yesCard).getByRole("button", { name: "Edit" }));
    fireEvent.click(within(yesCard).getByRole("button", { name: "Add an action" }));
    fireEvent.change(within(yesCard).getByLabelText("Action"), {
      target: { value: "collect_payment" },
    });
    // Move the split above the second reminder, then delete the first reminder.
    fireEvent.click(screen.getByRole("button", { name: "Move Step 3 up" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete Step 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(putBody(calls)).toBeDefined());
    expect(putBody(calls)?.steps).toEqual([
      {
        type: "branch",
        if: { predicate: "invoice.auto_pay" },
        then: [{ type: "action", action: "collect_payment", config: {} }],
        else: [],
      },
      CHASING.steps[2],
      CHASING.steps[3],
    ]);
  });

  it("edits a start near a date in hours and saves and switches on", async () => {
    const calls = editor(REMINDERS);
    render(<App />);
    const start = await screen.findByRole("region", { name: "Start" });
    expect(
      within(start).getByText("24 hours before and 2 hours before “Start” on the lesson"),
    ).toBeInTheDocument();
    expect(within(start).getByText("The lesson is still going ahead")).toBeInTheDocument();
    fireEvent.click(within(start).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(start).getAllByLabelText("Hours")[1] as HTMLElement, {
      target: { value: "1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and switch on" }));
    await waitFor(() => expect(putBody(calls)).toBeDefined());
    expect(putBody(calls)).toMatchObject({
      enabled: true,
      trigger_config: { subject: "lesson", field: "start", minutes: [-1440, -60] },
      conditions: { predicate: "lesson.still_planned" },
    });
  });

  it("pauses a workflow", async () => {
    const calls = editor(CHASING, {
      "POST /api/v1/workflows/w2/pause": { body: { ...CHASING, paused: true } },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));
    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.getByText(/^Paused: runs under way are held/)).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/w2/pause"))).toBe(true);
  });

  it("resets an edited built-in to the default", async () => {
    const calls = editor(CHASING, {
      "POST /api/v1/workflows/w2/reset-to-default": {
        body: { ...CHASING, edited: false, version: 2,
                builtin: { ...CHASING.builtin, update_available: false } },
      }, // prettier-ignore
    });
    vi.stubGlobal("confirm", () => true);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Reset to default" }));
    expect(await screen.findByText("Reset to the default.")).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/w2/reset-to-default"))).toBe(true);
  });

  it("makes a new workflow from a start, a message and a saved reply", async () => {
    window.history.pushState(null, "", "/workflows/new");
    const created = { ...INVOICING, id: "w9", kind: "custom", builtin: null, name: "Thank you" };
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/workflow-schema": { body: SCHEMA },
      "GET /api/v1/automation-schema": { body: FIELDS },
      "GET /api/v1/canned-replies": {
        body: { results: [{ id: "c1", title: "Thanks for paying" }], next: null, previous: null },
      },
      "POST /api/v1/workflows": { status: 201, body: created },
      "GET /api/v1/workflows/w9": { body: created },
      "GET /api/v1/workflows/w9/runs": { body: [] },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Thank you" } });
    const start = screen.getByRole("region", { name: "Start" });
    fireEvent.change(within(start).getByLabelText("What happens"), {
      target: { value: "invoice.paid" },
    });
    fireEvent.click(
      screen.getAllByRole("button", { name: /^Add a step at/ }).at(-1) as HTMLElement,
    );
    const card = screen.getByRole("region", { name: "Step 1" });
    expect(within(card).getByText("Choose what to do", { selector: "li" })).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Add an action" }));
    fireEvent.change(within(card).getByLabelText("Action"), {
      target: { value: "send_saved_reply" },
    });
    expect(within(card).getByText("Choose which message to send")).toBeInTheDocument();
    await within(card).findByRole("option", { name: "Thanks for paying" });
    fireEvent.change(within(card).getByLabelText("Saved message *"), {
      target: { value: "c1" },
    });
    fireEvent.click(within(card).getByLabelText("After a while"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      name: "Thank you",
      trigger_type: "event",
      trigger_config: { event: "invoice.paid" },
      steps: [
        { type: "wait", days: 1 },
        { type: "action", action: "send_saved_reply", config: { template: "c1" } },
      ],
    });
  });
});
