import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const PERMISSIONS = {
  "scheduling.lesson.view": "all",
  "matching.search": "all",
  "billing.invoice.view": "all",
  "payroll.view": "all",
  "recruitment.application.view": "all",
  "compliance.view": "all",
  "people.tutor.view": "all",
  "people.tutor.create": "all",
  "reporting.finance.view": "all",
  "reporting.payroll.view": "all",
};

const money = (value: string) => ({ label: "", currency: "GBP", value, previous: null });

function routes(mode: "solo" | "multi", teaches = false) {
  return {
    "GET /api/v1/me": {
      body: {
        ...ME,
        organisation: { ...ME.organisation, mode },
        membership: { ...ME.membership, role: "owner", teaches },
        permissions: PERMISSIONS,
      },
    },
    "GET /api/v1/organisation": {
      body: { ...ME.organisation, mode, timezone: "Europe/London", default_currency: "GBP" },
    },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/reporting/widgets/revenue": { body: { values: [money("120.00")] } },
    "GET /api/v1/reporting/widgets/outstanding": { body: { values: [money("0"), money("0")] } },
    "GET /api/v1/reporting/widgets/uninvoiced": { body: { values: [money("40.00")] } },
    "GET /api/v1/reporting/widgets/next_pay_run": { body: { values: [money("300.00")] } },
  };
}

describe("sole traders", () => {
  it("don't see the menus for running a team of tutors", async () => {
    mockApi(routes("solo"));
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(await within(nav).findByRole("link", { name: "Billing" })).toBeInTheDocument();
    for (const name of ["Matching", "Payroll", "Recruitment", "Compliance"]) {
      expect(within(nav).queryByRole("link", { name })).not.toBeInTheDocument();
    }
  });

  it("see what is ready to invoice instead of the next pay run", async () => {
    mockApi(routes("solo"));
    render(<App />);
    const strip = await screen.findByRole("region", { name: "Money this month" });
    expect(await within(strip).findByText("£40.00")).toBeInTheDocument();
    expect(within(strip).getByRole("link", { name: "Not yet invoiced" })).toBeInTheDocument();
    expect(within(strip).queryByText("Next pay run")).not.toBeInTheDocument();
  });

  it("can open the tutor app from the account menu once they teach", async () => {
    mockApi(routes("solo", true));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Account menu/ }));
    expect(screen.getByRole("link", { name: "Open the tutor app" })).toHaveAttribute(
      "href",
      "/portal/tutor",
    );
  });
});

describe("teams", () => {
  it("keep matching, payroll, recruitment and compliance", async () => {
    mockApi(routes("multi"));
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Main" });
    for (const name of ["Matching", "Payroll", "Recruitment", "Compliance"]) {
      expect(await within(nav).findByRole("link", { name })).toBeInTheDocument();
    }
  });
});

describe("adding yourself as a tutor", () => {
  it("makes the signed-in person a tutor, then the button goes", async () => {
    window.history.pushState(null, "", "/tutors");
    let teaches = false;
    const calls = mockApi({
      ...routes("solo"),
      "GET /api/v1/me": () => ({
        body: {
          ...ME,
          organisation: { ...ME.organisation, mode: "solo" },
          membership: { ...ME.membership, role: "owner", teaches },
          permissions: PERMISSIONS,
        },
      }),
      "GET /api/v1/tutors": { body: { next: null, previous: null, results: [] } },
      "POST /api/v1/tutors/add-me": () => {
        teaches = true;
        return { body: { id: "t1", full_name: "Sam Rivers" } };
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Add yourself as a tutor" }));
    await vi.waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/api/v1/tutors/add-me")).toBe(
        true,
      ),
    );
    await vi.waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Add yourself as a tutor" }),
      ).not.toBeInTheDocument(),
    );
  });
});
