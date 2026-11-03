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
    "pathway.view": "all",
    "pathway.manage": "all",
    "pathway.run.manage": "all",
    "pathway.step.complete": "all",
  },
};
const BASE = {
  "GET /api/v1/me": { body: OWNER },
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};
const SCHEMA = {
  step_types: [
    { key: "sign", label: "Sign an agreement", assignees: ["participant"] },
    { key: "staff_review", label: "Staff review", assignees: ["staff"] },
    { key: "show_check", label: "Show a check", assignees: ["participant"] },
  ],
  record_types: [{ key: "job", label: "Job" }],
  questions: [],
  roles: ["coordinator"],
  requirements: [{ key: "photo_id", name: "Photo ID" }],
};
const JOIN = {
  id: "p1", key: "join_job", name: "Join a job", description: "", kind: "join",
  record_type: "job", active: true, builtin_key: "join_job", edited: true,
  update_available: false, used_by_default: false, version: 2,
  stages: [{ key: "before", name: "Before your first lesson", gate: "ready", steps: [
    { key: "agreement", type: "sign", name: "Sign the job agreement", assignee: "participant",
      role: "", due_days: 3, config: { title: "Job agreement", text: "I agree." } },
  ] }],
  created_at: "2026-11-01T09:00:00Z", updated_at: "2026-11-01T09:00:00Z",
}; // prettier-ignore

describe("Settings › Pathways (E34-T02)", () => {
  it("lists ready-made pathways and makes one start on its own", async () => {
    window.history.pushState(null, "", "/settings/pathways");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/pathway-templates": { body: [JOIN] },
      "PATCH /api/v1/pathway-templates/p1": { body: { ...JOIN, used_by_default: true } },
    });
    render(<App />);
    expect(await screen.findByRole("link", { name: "Join a job" })).toBeInTheDocument();
    expect(screen.getByText(/Changed from the default/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Start Join a job on its own" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ used_by_default: true }),
    );
  });

  it("adds a step to a stage, saves, and resets to the default", async () => {
    window.history.pushState(null, "", "/settings/pathways/p1");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/pathway-templates/p1": { body: JOIN },
      "GET /api/v1/pathway-schema": { body: SCHEMA },
      "PATCH /api/v1/pathway-templates/p1": { body: JOIN },
      "POST /api/v1/pathway-templates/p1/reset-to-default": { body: { ...JOIN, edited: false } },
    });
    render(<App />);
    const stage = await screen.findByRole("heading", { name: /Stage 1: Before your first lesson/ });
    expect(stage).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("New step"), { target: { value: "show_check" } });
    fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
    fireEvent.change(screen.getByLabelText("Check"), { target: { value: "photo_id" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const body = calls.find((c) => c.method === "PATCH")?.body as {
      stages: { steps: { type: string; config: Record<string, unknown> }[] }[];
    };
    expect(body.stages[0]?.steps.map((s) => s.type)).toEqual(["sign", "show_check"]);
    expect(body.stages[0]?.steps[1]?.config).toEqual({ requirement: "photo_id" });
    fireEvent.click(screen.getByRole("button", { name: "Reset to default" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/reset-to-default"))).toBe(true));
  });

  it("says what stops a pathway saving", async () => {
    window.history.pushState(null, "", "/settings/pathways/new");
    mockApi({ ...BASE, "GET /api/v1/pathway-schema": { body: SCHEMA } });
    render(<App />);
    expect(await screen.findByText("Give the pathway a name.")).toBeInTheDocument();
    expect(screen.getByText("Add a step to stage 1.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});

describe("pathway timelines on a job (E34-T02)", () => {
  const RUN = {
    id: "r1", template: "p1", template_name: "Join a job", template_key: "join_job",
    kind: "join", version: 1, record_type: "job", record_id: "j1",
    tutor: { id: "t1", name: "Ada Lovelace" }, status: "running", stage: "before",
    stages: [{ key: "before", name: "Before your first lesson", gate: "ready" }], gates: [],
    progress: { finished: 0, total: 1 }, started_at: "2026-11-01T09:00:00Z",
    finished_at: null, reason: "",
  }; // prettier-ignore
  const STEP = {
    id: "s1", key: "check", stage: "before", name: "Coordinator check",
    step_type: "staff_review", assignee: "staff", role: "", status: "open", due_at: null,
    opened_at: "2026-11-01T09:00:00Z", submitted_at: null, completed_at: null,
    completed_by: null, config: {}, result: {}, reason: "",
  }; // prettier-ignore

  it("turns a staff review down with a reason", async () => {
    window.history.pushState(null, "", "/settings/pathways");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/pathway-templates": { body: [] },
      "GET /api/v1/pathway-runs": { body: { results: [RUN], next: null, previous: null } },
      "GET /api/v1/pathway-runs/r1": { body: { ...RUN, steps: [STEP] } },
      "POST /api/v1/pathway-runs/r1/steps/check/reject": { body: { ...STEP, status: "rejected" } },
    });
    const { PathwayRunsPanel } = await import("./PathwayRuns");
    const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PathwayRunsPanel jobId="j1" />
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Steps of Join a job" }));
    const row = (await screen.findByText("Coordinator check")).closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Turn down: Coordinator check" }));
    fireEvent.change(within(row).getByLabelText("Reason"), { target: { value: "Not ready" } });
    fireEvent.click(within(row).getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/reject"))?.body).toEqual({ reason: "Not ready" }),
    );
    expect(calls.find((c) => c.path === "/api/v1/pathway-runs")?.search).toContain(
      "record_type=job",
    );
  });
});
