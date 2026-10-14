import { fireEvent, render, screen, waitFor } from "@testing-library/react";

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

const SCHEMA = {
  subjects: [
    {
      key: "package",
      label: "Package",
      recipients: ["client", "owner"],
      setters: [],
      date_fields: ["expires_at"],
      taggable: false,
      fields: [
        { path: "package.units_remaining", label: "Units left", type: "number", choices: [] },
      ],
    },
  ],
  triggers: [{ event: "package.low", label: "Package running low", subject: "package" }],
  actions: [
    {
      key: "send_saved_reply",
      label: "Send a saved message",
      subjects: [],
      permission: "",
      allowed: true,
      fields: [
        { name: "to", label: "To", type: "multi", required: true, choices: ["client"] },
        { name: "template", label: "Saved message", type: "saved_reply", required: true, choices: [] },
      ],
    },
    {
      key: "add_to_mailing_list",
      label: "Add to a mailing list",
      subjects: [],
      permission: "",
      allowed: true,
      fields: [
        { name: "list", label: "List name", type: "text", required: true, choices: [] },
        { name: "sync", label: "Sync to Mailchimp/Brevo", type: "bool", required: false, choices: [] },
      ],
    },
  ],
  operators: ["lt"],
  predicates: {},
}; // prettier-ignore

describe("automations (G4)", () => {
  it("picks a saved message and a mailing list in the builder", async () => {
    window.history.pushState(null, "", "/automations/new");
    const calls = mockApi({
      "GET /api/v1/me": { body: ADMIN },
      "GET /api/v1/organisation": { body: { status: "active" } },
      "GET /api/v1/me/organisations": { body: [] },
      "GET /api/v1/automation-schema": { body: SCHEMA },
      "GET /api/v1/canned-replies": {
        body: { results: [{ id: "c1", title: "Top up", body: "Hi", shortcut: "" }], next: null },
      },
      "POST /api/v1/automations": { status: 400, body: { title: "stop", status: 400 } },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Low" } });
    fireEvent.change(screen.getByLabelText("Event"), { target: { value: "package.low" } });
    fireEvent.click(screen.getByRole("button", { name: "Add an action" }));
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "send_saved_reply" } });
    const saved = await screen.findByLabelText("Saved message *");
    expect(await screen.findByRole("option", { name: "Top up" })).toBeInTheDocument();
    fireEvent.change(saved, { target: { value: "c1" } });
    fireEvent.click(screen.getByRole("button", { name: "Add an action" }));
    const selects = screen.getAllByLabelText("Action");
    fireEvent.change(selects[1]!, { target: { value: "add_to_mailing_list" } });
    expect(screen.getByLabelText("Sync to Mailchimp/Brevo")).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const posted = calls.find((c) => c.method === "POST")?.body as {
      steps: { action: string; config: Record<string, unknown> }[];
    };
    expect(posted.steps[0]).toMatchObject({
      action: "send_saved_reply",
      config: { template: "c1" },
    });
  });
});
