import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const BASE = {
  "GET /api/v1/me": { body: { membership: { role: "tutor" }, user: { email: "n@x.com" } } },
  "GET /api/v1/tutor/me": {
    body: { id: "t1", name: "Nia", email: "n@x.com", can_cancel: true, can_edit_lessons: false,
            can_see_pay: true },
  }, // prettier-ignore
};

describe("tutor onboarding", () => {
  it("ticks an agreement", async () => {
    window.history.pushState(null, "", "/portal/tutor/onboarding");
    const item = { key: "agreement", label: "Sign the tutor agreement", kind: "agreement",
                   mandatory: true, done: false, done_at: null }; // prettier-ignore
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/me/onboarding": { body: { items: [item], completed_at: null } },
      "POST /api/v1/me/onboarding/agreement/done": {
        body: { items: [{ ...item, done: true }], completed_at: null },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Mark done" }));
    expect(await screen.findByText("Done")).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/agreement/done"))).toBe(true);
  });

  it("sends a DBS number for checking", async () => {
    window.history.pushState(null, "", "/portal/tutor/compliance");
    const requirement = { id: "r1", key: "dbs_enhanced", name: "Enhanced DBS check",
                          has_number: true, has_expiry: true }; // prettier-ignore
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/me/compliance": {
        body: { restricted: true, problems: ["dbs_enhanced"], requirements: [requirement],
                records: [] },
      }, // prettier-ignore
      "POST /api/v1/me/compliance": {
        body: { restricted: true, problems: [], requirements: [requirement],
                records: [{ id: "c1", requirement: "r1", status: "submitted", valid: false }] },
      }, // prettier-ignore
    });
    render(<App />);
    expect(await screen.findByText(/can't take new lessons/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Reference number"), { target: { value: "0012345" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/Being checked/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      requirement: "r1",
      number: "0012345",
    });
  });
});
