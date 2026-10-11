import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const PERMS = {
  ...ME.permissions,
  "migration.import.view": "all",
  "migration.import.manage": "all",
  "migration.project.manage": "all",
  "migration.export.full": "all",
};

const FIELD = (key: string, label: string, required = false, choices: string[] = []) => ({
  key,
  label,
  field_type: choices.length ? "choice" : "text",
  required,
  choices,
  help: "",
});

const CATALOGUE = {
  entities: [
    {
      key: "students",
      label: "Students",
      description: "Learners.",
      field_specs: [FIELD("first_name", "First name", true)],
      upsert_keys: ["external_id", "none"],
      default_upsert: "external_id",
      permissions: [],
      allowed: true,
    },
  ],
  presets: { tutorbird: ["students"] },
};

const BATCH = {
  id: "b1",
  entity: "students",
  origin: "csv",
  preset: "",
  filename: "students.csv",
  sheet: "",
  status: "mapping",
  stats: { rows: 2 },
  error: "",
  error_file: null,
  project: null,
  project_step: "",
  requested_by: null,
  created_at: "2026-10-10T10:00:00Z",
  validated_at: null,
  confirmed_at: null,
  completed_at: null,
  rollback_until: null,
  rolled_back_at: null,
  finalised_at: null,
  can_rollback: false,
  options: {},
};

const PREVIEW = {
  headers: ["First Name", "State"],
  column_map: { "First Name": "first_name", State: "" },
  value_map: {},
  options: {},
  sample: [{ "First Name": "Ava", State: "Gone" }],
  distinct: {},
  field_specs: [
    FIELD("first_name", "First name", true),
    FIELD("status", "Status", false, ["active", "finished"]),
  ],
  upsert_keys: ["external_id", "none"],
  missing_required: [],
};

const ROW = {
  id: "r2",
  row_number: 2,
  raw: { "First Name": "", State: "Gone" },
  values: {},
  status: "invalid",
  action: "",
  row_errors: [{ field: "first_name", message: "First name is required." }],
  row_warnings: [],
  target_type: "",
  target_id: "",
  applied_at: null,
};

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
    "GET /api/v1/organisation": { body: { status: "active" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/import-catalogue": { body: CATALOGUE },
    "GET /api/v1/imports": { body: { results: [BATCH] } },
    "GET /api/v1/imports/b1": { body: BATCH },
    "GET /api/v1/imports/b1/preview": { body: PREVIEW },
    "GET /api/v1/imports/b1/rows": { body: { results: [ROW] } },
    ...extra,
  };
}

describe("import and export", () => {
  it("uploads a file, waits for the scan and opens the mapping", async () => {
    window.history.pushState(null, "", "/data");
    const calls = mockApi(
      routes({
        "POST /api/v1/files/uploads": {
          status: 201,
          body: {
            file: { id: "f1" },
            upload: { url: "http://s3.test/upload", method: "PUT", headers: {}, expires_in: 900 },
          },
        },
        "POST /api/v1/files/f1/complete": { body: { id: "f1", scan_status: "skipped" } },
        "POST /api/v1/imports": { status: 201, body: BATCH },
      }),
    );
    // The browser PUTs the bytes straight to storage (a plain URL, not an API request).
    const apiFetch = globalThis.fetch;
    const storage = vi.fn(
      async (_url: string, _init?: RequestInit) => new Response(null, { status: 200 }),
    );
    vi.stubGlobal("fetch", (input: RequestInfo, init?: RequestInit) =>
      typeof input === "string" ? storage(input, init) : apiFetch(input),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Import and export" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "students.csv" })).toBeInTheDocument();
    const input = await screen.findByLabelText("File (CSV or .xlsx)");
    fireEvent.change(input, {
      target: { files: [new File(["First Name\nAva\n"], "students.csv", { type: "text/csv" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload and match columns" }));
    expect(await screen.findByRole("heading", { name: "Match your columns" })).toBeInTheDocument();
    expect(storage).toHaveBeenCalledWith("http://s3.test/upload", expect.anything());
    expect(calls.find((c) => c.path === "/api/v1/imports" && c.method === "POST")?.body).toEqual({
      file: "f1",
      entity: "students",
      preset: "",
      sheet: "",
      project: null,
      project_step: "",
    });
  });

  it("maps columns and starts the check", async () => {
    window.history.pushState(null, "", "/data/imports/b1");
    const calls = mockApi(
      routes({
        "PUT /api/v1/imports/b1/mapping": { body: PREVIEW },
        "POST /api/v1/imports/b1/submit": { body: { ...BATCH, status: "validating" } },
      }),
    );
    render(<App />);
    const select = await screen.findByLabelText("Field for “State”");
    fireEvent.change(select, { target: { value: "status" } });
    fireEvent.click(screen.getByRole("button", { name: "Check the rows" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/submit"))).toBe(true));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.body).toMatchObject({
      column_map: { "First Name": "first_name", State: "status" },
    });
  });

  it("shows the dry run and the rows with errors, then confirms", async () => {
    window.history.pushState(null, "", "/data/imports/b1");
    const validated = {
      ...BATCH,
      status: "validated",
      stats: {
        rows: 2,
        valid: 1,
        invalid: 1,
        warnings: 0,
        will: { "people.student": { create: 1 } },
      },
    };
    const calls = mockApi(
      routes({
        "GET /api/v1/imports/b1": { body: validated },
        "POST /api/v1/imports/b1/confirm": { body: { ...validated, status: "importing" } },
      }),
    );
    render(<App />);
    expect(await screen.findByText("Create 1 students")).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Rows of the file with their checks" });
    expect(within(table).getByText("First name is required.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import 1 rows" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/confirm"))).toBe(true));
  });

  it("offers the error report and rollback after the import", async () => {
    window.history.pushState(null, "", "/data/imports/b1");
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const done = {
      ...BATCH,
      status: "completed",
      error_file: "e1",
      can_rollback: true,
      rollback_until: "2026-10-17T10:00:00Z",
      stats: { rows: 2, created: 1, invalid: 1 },
    };
    const calls = mockApi(
      routes({
        "GET /api/v1/imports/b1": { body: done },
        "GET /api/v1/imports/b1/error-report": {
          body: { url: "https://s3.test/errors.csv", expires_in: 900 },
        },
        "POST /api/v1/imports/b1/rollback": { body: { ...done, status: "rolling_back" } },
      }),
    );
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Download the rows that weren't imported" }),
    );
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://s3.test/errors.csv"));
    fireEvent.click(screen.getByRole("button", { name: /Roll back/ }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/rollback"))).toBe(true));
  });

  it("walks a migration step by step and shows the reconciliation", async () => {
    window.history.pushState(null, "", "/data");
    const project = {
      id: "p1",
      name: "From TutorCruncher",
      origin: "tutorcruncher",
      cutover_date: "2026-11-01",
      status: "active",
      current_step: "payment_methods",
      steps: { people: { status: "done" }, payment_methods: { status: "in_progress" } },
      source_totals: {},
      reconciliation: {
        ok: false,
        lines: [{ metric: "clients", source: "2", imported: "1", difference: "-1", ok: false }],
      },
      connection_name: "API key",
      created_at: "2026-10-10T10:00:00Z",
      completed_at: null,
      batches: [],
    };
    const calls = mockApi(
      routes({
        "GET /api/v1/migration-projects": { body: { results: [project] } },
        "POST /api/v1/migration-projects/p1/steps/payment_methods/complete": { body: project },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Move from another system" }));
    expect(await screen.findByText("Payment methods", { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "This step is done" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path.endsWith("/payment_methods/complete"))).toBe(true),
    );
    const table = screen.getByRole("table", { name: "Reconciliation" });
    expect(within(table).getByText("-1")).toBeInTheDocument();
  });

  it("downloads the full export after confirming the password", async () => {
    window.history.pushState(null, "", "/data/export");
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const calls = mockApi(
      routes({
        "GET /api/v1/data-exports": {
          body: {
            results: [
              {
                id: "x1",
                kind: "full",
                status: "ready",
                reason: "owner",
                requested_by: null,
                progress: {},
                size_bytes: 1000,
                error: "",
                created_at: "2026-10-10T10:00:00Z",
                ready_at: "2026-10-10T10:05:00Z",
                expires_at: "2026-10-17T10:05:00Z",
                downloaded_at: null,
                download_count: 0,
              },
            ],
          },
        },
        "POST /api/v1/data-exports/x1/download": {
          body: { url: "https://s3.test/export.zip", expires_in: 300 },
        },
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Confirm your password"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://s3.test/export.zip"));
    expect(calls.find((c) => c.path.endsWith("/download"))?.body).toEqual({ password: "secret" });
  });
});
