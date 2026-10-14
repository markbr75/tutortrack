import { createI18n, I18nextProvider } from "@tutortrack/i18n";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { AttentionReasons } from "./g3/JobAttention";
import { BulkPayments, RunTutorReviews } from "./g3/BillingExtras";
import { BulkLessonBar, SavedFilterSets } from "./g3/CalendarTools";
import { KeyedSettings } from "./g3/KeyedSettings";
import { FullBankDetails, RunItems } from "./g3/PayrollExtras";
import { PolicyOverrides } from "./g3/DeliveryOverrides";
import { timeIn } from "./g3/zones";
import { ME, mockApi } from "./test-utils";
import type { CalendarItem } from "./calendar/types";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
});

function signedIn(permissions: Record<string, string>, extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions: { ...ME.permissions, ...permissions } } },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
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

const PAGE = (results: unknown[]) => ({ next: null, previous: null, results });

describe("G3: jobs needing attention", () => {
  it("labels each reason", () => {
    wrap(<AttentionReasons reasons={["no_upcoming_lessons", "low_balance"]} />);
    expect(screen.getByText("No upcoming lessons")).toBeInTheDocument();
    expect(screen.getByText("Low balance")).toBeInTheDocument();
  });
});

describe("G3: calendar tools", () => {
  it("saves the current filters as a named set and applies a saved one", async () => {
    const saved = { id: "v1", entity_type: "calendar", name: "Nia's week", filters: { view: "agenda", tutor: "t1", status: "planned", colourBy: "tutor" }, owner: "u1", created_at: "2026-10-14T09:00:00Z" }; // prettier-ignore
    const calls = mockApi(
      signedIn(
        {},
        {
          "GET /api/v1/saved-views": { body: [saved] },
          "POST /api/v1/saved-views": { status: 201, body: { ...saved, id: "v2" } },
        },
      ),
    );
    const onApply = vi.fn();
    wrap(
      <SavedFilterSets
        current={{ view: "week", tutor: "", status: "", colourBy: "service" }}
        onApply={onApply}
      />,
    );
    await screen.findByRole("option", { name: "Nia's week" });
    fireEvent.change(screen.getByLabelText("Saved filters"), { target: { value: "v1" } });
    expect(onApply).toHaveBeenCalledWith(saved.filters);
    fireEvent.change(screen.getByLabelText("Name for these filters"), {
      target: { value: "Mine" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save filters" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        entity_type: "calendar",
        name: "Mine",
        filters: { view: "week" },
      }),
    );
  });

  it("formats times in a second time zone", () => {
    const at = new Date("2026-07-01T15:00:00Z");
    expect(timeIn(at, "America/New_York", "en-GB")).toBe("11:00");
  });

  it("runs a bulk action and keeps failed lessons selected", async () => {
    const calls = mockApi(
      signedIn(
        { "scheduling.lesson.edit": "all" },
        {
          "POST /api/v1/lessons/bulk": {
            body: { succeeded: ["l1"], failed: { l2: "Only planned lessons can be cancelled." } },
          },
        },
      ),
    );
    const items = [
      { id: "l1", kind: "lesson", title: "Maths", start: "2026-10-20T15:00:00Z", end: "2026-10-20T16:00:00Z", tutors: [], status: "planned", online: true, location: "" },
      { id: "l2", kind: "lesson", title: "English", start: "2026-10-21T15:00:00Z", end: "2026-10-21T16:00:00Z", tutors: [], status: "completed", online: true, location: "" },
    ] as unknown as CalendarItem[]; // prettier-ignore
    const onDone = vi.fn();
    wrap(<BulkLessonBar selected={["l1", "l2"]} items={items} tutors={[]} onDone={onDone} />);
    expect(await screen.findByText("2 lessons selected")).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("Action"), { target: { value: "cancel" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply to selected" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(["l2"]));
    expect(calls.find((c) => c.path === "/api/v1/lessons/bulk")?.body).toMatchObject({
      action: "cancel",
      ids: ["l1", "l2"],
    });
  });
});

describe("G3: delivery policy overrides", () => {
  it("sets a policy for one service", async () => {
    const calls = mockApi(
      signedIn(
        { "delivery.policy.manage": "all" },
        {
          "GET /api/v1/cancellation-policies": { body: [] },
          "GET /api/v1/catalogue/services": { body: PAGE([{ id: "s1", name: "Maths 1:1" }]) },
          "POST /api/v1/cancellation-policies": { status: 201, body: {} },
        },
      ),
    );
    wrap(<PolicyOverrides />);
    await screen.findByRole("option", { name: "Maths 1:1" });
    fireEvent.change(screen.getByLabelText("Service"), { target: { value: "s1" } });
    fireEvent.change(await screen.findByLabelText("Free cancellations per term"), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save policy" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        scope_type: "service",
        scope_id: "s1",
        name: "Service: Maths 1:1",
        rules: { max_free_per_term: 2 },
      }),
    );
  });
});

describe("G3: billing", () => {
  it("shows tutors' answers on a run", async () => {
    mockApi(
      signedIn(
        {},
        {
          "GET /api/v1/invoice-runs/r1/tutor-reviews": {
            body: [{ id: "x", tutor_name: "Nia", status: "flagged", comment: "Wrong date" }],
          },
        },
      ),
    );
    wrap(<RunTutorReviews runId="r1" />);
    expect(await screen.findByText("Problem reported", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/Wrong date/)).toBeInTheDocument();
  });

  it("records several payments with an idempotency key", async () => {
    const calls = mockApi(
      signedIn(
        { "payments.payment.record": "all" },
        {
          "GET /api/v1/clients": { body: PAGE([{ id: "c1", display_name: "The Patels" }]) },
          "POST /api/v1/payments/bulk": { status: 201, body: [{ id: "p1" }] },
        },
      ),
    );
    wrap(<BulkPayments />);
    await screen.findAllByRole("option", { name: "The Patels" });
    fireEvent.change(screen.getByLabelText("Client, row 1"), { target: { value: "c1" } });
    fireEvent.change(screen.getByLabelText("Amount, row 1"), { target: { value: "40.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Record 1 payment" }));
    expect(await screen.findByText("1 payment recorded.")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({
      rows: [{ client: "c1", amount: { amount: "40.00", currency: "GBP" }, method: "bank_transfer" }],
    });
  });

  it("edits chosen settings, including a list of choices", async () => {
    const calls = mockApi(
      signedIn(
        { "org.settings.manage": "all" },
        {
          "GET /api/v1/settings/payments": {
            body: {
              area: "payments", branch: "b1", overrides: [],
              values: { "payments.enabled_methods": ["card", "cash"], "payments.card_surcharge_percent": "0" },
              schema: [
                { key: "payments.enabled_methods", type: "object", label: "Ways this branch takes payment", schema: { items: { enum: ["card", "cash"] } } },
                { key: "payments.card_surcharge_percent", type: "str", label: "Card surcharge (%)" },
              ],
            },
          },
          "PATCH /api/v1/settings/payments": (body) => ({ body: { area: "payments", values: (body as { values: object }).values, schema: [], overrides: [] } }),
        },
      ),
    ); // prettier-ignore
    wrap(
      <KeyedSettings
        area="payments"
        branch="b1"
        keys={["payments.enabled_methods", "payments.card_surcharge_percent"]}
        label="Payments"
      />,
    );
    fireEvent.click(await screen.findByLabelText("cash"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH");
      expect(patch?.search).toBe("?branch=b1");
      expect(patch?.body).toMatchObject({ values: { "payments.enabled_methods": ["card"] } });
    });
  });
});

describe("G3: payroll", () => {
  it("asks to re-authenticate before showing full bank details", async () => {
    let confirmed = false;
    mockApi(
      signedIn(
        { "payroll.bank_details.view": "all" },
        {
          "GET /api/v1/tutors/t1/pay-profile": () =>
            confirmed
              ? { body: { bank: { account_number: "12345678", sort_code: "30-96-34" } } }
              : {
                  status: 403,
                  body: { type: "https://tutortrack.app/problems/reauthentication-required", status: 403, title: "x", methods: ["password"] },
                },
          "GET /api/v1/auth/reauthenticate": { body: { recent: false, methods: ["password"] } },
          "POST /api/v1/auth/reauthenticate": () => {
            confirmed = true;
            return { body: { recent: true, methods: ["password"] } };
          },
        },
      ),
    ); // prettier-ignore
    wrap(<FullBankDetails tutorId="t1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Show full bank details" }));
    fireEvent.change(await screen.findByLabelText("Your password"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("12345678")).toBeInTheDocument();
  });

  it("edits an item in a run under review", async () => {
    const calls = mockApi(
      signedIn(
        { "payroll.payrun.create": "all" },
        {
          "GET /api/v1/pay-items": {
            body: PAGE([
              { id: "i1", tutor_name: "Nia", kind: "lesson", description: "Maths", amount: { amount: "25.00", currency: "GBP" }, adjusts: null },
              { id: "i2", tutor_name: "Nia", kind: "adjustment", description: "Correction", amount: { amount: "5.00", currency: "GBP" }, adjusts: "i1" },
            ]),
          },
          "POST /api/v1/pay-runs/r1/edit-item": { body: {} },
        },
      ),
    ); // prettier-ignore
    wrap(<RunItems runId="r1" editable />);
    expect(await screen.findByText(/Correction/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit Maths" }));
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "30.00" } });
    fireEvent.change(screen.getByLabelText("Why it changes"), { target: { value: "Longer" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        item: "i1",
        amount: { amount: "30.00", currency: "GBP" },
        reason: "Longer",
      }),
    );
  });
});
