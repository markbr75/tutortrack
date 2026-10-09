import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const ADMIN = {
  ...ME.permissions,
  "catalogue.view": "all",
  "catalogue.manage": "all",
  "rates.manage": "all",
  "billing.rates.view_charge": "all",
  "billing.rates.view_pay": "all",
};

const SERVICE = {
  id: "sv1",
  name: "GCSE Maths 1:1",
  pricing_unit: "per_hour",
  format: "one_to_one",
  currency: "GBP",
  charge_rate: { amount: "40.0000", currency: "GBP" },
  pay_rate: { amount: "25.0000", currency: "GBP" },
  pay_percent: null,
  prices: [],
  active: true,
};

function base(permissions: Record<string, string>) {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions } },
    "GET /api/v1/organisation": { body: { status: "active", default_currency: "GBP" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/catalogue/services": { body: { results: [SERVICE], next: null } },
    "GET /api/v1/catalogue/tax-rates": {
      body: [{ id: "tx1", name: "Exempt", percent: "0.000", is_default: true }],
    },
  };
}

describe("catalogue", () => {
  it("lists services with rates and creates one", async () => {
    window.history.pushState(null, "", "/catalogue");
    const calls = mockApi({
      ...base(ADMIN),
      "POST /api/v1/catalogue/services": { status: 201, body: { ...SERVICE, id: "sv2" } },
    });
    render(<App />);
    const row = (await screen.findByText("GCSE Maths 1:1")).closest("tr")!;
    expect(within(row).getByText("£40.00")).toBeInTheDocument();
    expect(within(row).getByText("£25.00")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Piano" } });
    fireEvent.change(screen.getByLabelText("Pricing"), { target: { value: "per_lesson" } });
    fireEvent.change(screen.getByLabelText("Charge rate"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("Tutor pay"), { target: { value: "percent" } });
    fireEvent.change(screen.getByLabelText("Pay (% of charge)"), { target: { value: "60" } });
    fireEvent.click(screen.getByRole("button", { name: "Create service" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        name: "Piano",
        pricing_unit: "per_lesson",
        charge_rate: { amount: "30", currency: "GBP" },
        pay_rate: null,
        pay_percent: "60",
      }),
    );
  });

  it("hides rates and editing from read-only roles", async () => {
    window.history.pushState(null, "", "/catalogue");
    mockApi(base({ ...ME.permissions, "catalogue.view": "all" }));
    render(<App />);
    await screen.findByText("GCSE Maths 1:1");
    expect(screen.queryByText("£40.00")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create service" })).not.toBeInTheDocument();
  });

  it("switches tabs with the keyboard and adds a subject", async () => {
    window.history.pushState(null, "", "/catalogue");
    let subjects = [
      { id: "sj1", name: "Maths", levels: [{ id: "l1", name: "GCSE" }], exam_boards: ["AQA"] },
    ];
    const calls = mockApi({
      ...base(ADMIN),
      "GET /api/v1/catalogue/subjects": () => ({ body: subjects }),
      "POST /api/v1/catalogue/subjects": (body) => {
        subjects = [
          ...subjects,
          { id: "sj2", name: (body as { name: string }).name, levels: [], exam_boards: [] },
        ];
        return { status: 201, body: subjects[1] };
      },
    });
    render(<App />);
    const servicesTab = await screen.findByRole("tab", { name: "Services" });
    servicesTab.focus();
    fireEvent.keyDown(servicesTab, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Subjects" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("GCSE · AQA")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("New subject"), { target: { value: "Latin" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("Latin")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/v1/catalogue/subjects")).toBe(
      true,
    );
  });

  it("checks a price and shows the trace", async () => {
    window.history.pushState(null, "", "/catalogue");
    const calls = mockApi({
      ...base(ADMIN),
      "GET /api/v1/students": {
        body: { results: [{ id: "s1", full_name: "Arjun Patel" }], next: null },
      },
      "GET /api/v1/tutors": {
        body: { results: [{ id: "t1", full_name: "Nia Okafor" }], next: null },
      },
      "POST /api/v1/rates/quote": {
        body: {
          currency: "GBP",
          duration_minutes: 90,
          total_charge: { amount: "60.00", currency: "GBP" },
          total_pay: { amount: "37.50", currency: "GBP" },
          charges: [
            {
              student_id: "s1",
              amount: { amount: "60.00", currency: "GBP" },
              trace: ["service rate £40.00/h", "90 minutes"],
            },
          ],
          pay: [
            {
              tutor_id: "t1",
              amount: { amount: "37.50", currency: "GBP" },
              trace: ["service pay rate £25.00/h", "90 minutes"],
            },
          ],
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Price check" }));
    fireEvent.change(await screen.findByLabelText("Service"), { target: { value: "sv1" } });
    fireEvent.change(screen.getByLabelText("Lesson length (minutes)"), { target: { value: "90" } });
    fireEvent.click(await screen.findByLabelText("Arjun Patel"));
    fireEvent.change(screen.getByLabelText("Tutor"), { target: { value: "t1" } });
    fireEvent.click(screen.getByRole("button", { name: "Check price" }));
    expect(await screen.findByText("service rate £40.00/h · 90 minutes")).toBeInTheDocument();
    expect(screen.getByText("Arjun Patel: £60.00")).toBeInTheDocument();
    expect(screen.getByText("Nia Okafor: £37.50")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/rates/quote")?.body).toEqual({
      service: "sv1",
      duration_minutes: 90,
      students: [{ student: "s1" }],
      tutors: [{ tutor: "t1" }],
      job_charge_rate: null,
    });
  });
});
