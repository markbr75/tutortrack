import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const ADMIN = {
  ...ME,
  permissions: { ...ME.permissions, "automation.view": "all", "automation.manage": "all" },
};
const BASE = {
  "GET /api/v1/me": { body: ADMIN },
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};

const SCHEMA = {
  subjects: [
    {
      key: "student", label: "Student", recipients: ["client", "owner"], setters: ["status"],
      date_fields: ["date_of_birth"], taggable: true,
      fields: [
        { path: "student.first_name", label: "First name", type: "text", choices: [] },
        { path: "student.status", label: "Status", type: "choice", choices: ["active", "paused"] },
      ],
    },
  ],
  triggers: [
    { event: "student.status_changed", label: "Student status changed", subject: "student" },
    { event: "lesson.completed", label: "Lesson completed", subject: "lesson" },
  ],
  actions: [
    {
      key: "send_message", label: "Send a message", subjects: [], permission: "", allowed: true,
      fields: [
        { name: "to", label: "To", type: "multi", required: true, choices: ["client", "tutor", "owner"] },
        { name: "channels", label: "Channels", type: "multi", required: true,
          choices: ["email", "sms", "in_app"] },
        { name: "body", label: "Message", type: "template", required: true, choices: [] },
      ],
    },
  ],
  operators: ["equals", "is_empty"],
  predicates: {},
}; // prettier-ignore

const AUTOMATION = {
  id: "a1", name: "Paused students", description: "", trigger_type: "event",
  trigger_config: { event: "student.status_changed" }, subject_type: "student",
  conditions: { all: [{ field: "student.status", op: "equals", value: "paused" }] },
  steps: [{ type: "action", action: "send_message",
            config: { to: ["client"], channels: ["email"], body: "Hi" } }],
  version: 2, enabled: false, max_runs_per_record: 1, recipe_key: "",
  created_at: "2026-10-10T09:00:00Z", updated_at: "2026-10-10T09:00:00Z",
}; // prettier-ignore

describe("automations", () => {
  it("builds an automation: when, if, then", async () => {
    window.history.pushState(null, "", "/automations/new");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/automation-schema": { body: SCHEMA },
      "POST /api/v1/automations": { status: 201, body: AUTOMATION },
      "GET /api/v1/automations/a1": { body: AUTOMATION },
      "GET /api/v1/automations/a1/runs": { body: [] },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Name"), {
      target: { value: "Paused students" },
    });
    fireEvent.change(screen.getByLabelText("Event"), {
      target: { value: "student.status_changed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add a condition" }));
    fireEvent.change(screen.getByLabelText("Field"), { target: { value: "student.status" } });
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "paused" } });
    fireEvent.click(screen.getByRole("button", { name: "Add an action" }));
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "send_message" } });
    fireEvent.click(screen.getByLabelText("Family"));
    fireEvent.click(screen.getByLabelText("Email"));
    fireEvent.change(screen.getByLabelText("Message *"), { target: { value: "Hi " } });
    fireEvent.change(screen.getByLabelText("Insert a variable"), {
      target: { value: "student.first_name" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByText(/version 2/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST" && c.path === "/api/v1/automations")?.body).toEqual({
      name: "Paused students", description: "", trigger_type: "event",
      trigger_config: { event: "student.status_changed" },
      conditions: { all: [{ field: "student.status", op: "equals", value: "paused" }] },
      steps: [{ type: "action", action: "send_message",
                config: { to: ["client"], channels: ["email"],
                          body: "Hi {{ student.first_name }}" } }],
      enabled: false, max_runs_per_record: 1,
    }); // prettier-ignore
  });

  it("tests an automation against a record", async () => {
    window.history.pushState(null, "", "/automations/a1");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/automation-schema": { body: SCHEMA },
      "GET /api/v1/automations/a1": { body: AUTOMATION },
      "GET /api/v1/automations/a1/runs": { body: [] },
      "POST /api/v1/automations/a1/test": {
        body: { matched: true, record: {},
                steps: [{ key: "0", type: "action", description: "Send email to 1 people: Hi Arjun",
                          ok: true }] },
      }, // prettier-ignore
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Record ID"), { target: { value: "s1" } });
    fireEvent.click(screen.getByRole("button", { name: "Test" }));
    expect(await screen.findByText(/Hi Arjun/)).toBeInTheDocument();
    expect(screen.getByText(/This record matches/)).toBeInTheDocument();
    expect(calls.find((c) => c.path.endsWith("/test"))?.body).toEqual({ subject_id: "s1" });
  });

  it("installs a recipe and retries a failed run", async () => {
    window.history.pushState(null, "", "/automations");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/automation-schema": { body: SCHEMA },
      "GET /api/v1/automations": { body: [] },
      "GET /api/v1/automation-recipes": {
        body: [{ key: "new_enquiry", name: "New enquiry: reply and follow up", description: "x",
                 trigger_type: "event", trigger_config: {}, installed: false }],
      }, // prettier-ignore
      "POST /api/v1/automation-recipes/new_enquiry/install": { status: 201, body: AUTOMATION },
      "GET /api/v1/automation-runs": {
        body: { results: [{ id: "r1", automation: "a1", automation_name: "Paused students",
                            version: 2, subject_type: "student", subject_id: "s1234567890",
                            event_type: "", status: "failed", started_at: "2026-10-10T09:00:00Z",
                            finished_at: null, causation_depth: 0, attempts: 1,
                            error: "The webhook failed" }], next: null, previous: null },
      }, // prettier-ignore
      "POST /api/v1/automation-runs/r1/retry": { body: {} },
    });
    render(<App />);
    expect(await screen.findByText(/No automations yet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Recipes" }));
    fireEvent.click(await screen.findByRole("button", { name: "Install" }));
    await vi.waitFor(() => expect(calls.some((c) => c.path.endsWith("/install"))).toBe(true));
    fireEvent.click(screen.getByRole("tab", { name: "Runs" }));
    const row = (await screen.findByText("The webhook failed")).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Retry from the failed step" }));
    await vi.waitFor(() => expect(calls.some((c) => c.path.endsWith("/r1/retry"))).toBe(true));
  });
});
