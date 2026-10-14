import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "./App";
import { mockApi } from "./test-utils";

type Routes = Parameters<typeof mockApi>[0];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
});

const FAMILY_ME = {
  role: "client",
  organisation: { name: "Bright Minds", primary_colour: "" },
  clients: [{ id: "c1", name: "The Patels" }, { id: "c2", name: "Grandma's" }],
  households: [{ id: "c1", name: "The Patels" }, { id: "c2", name: "Grandma's" }],
  household: "",
  students: [{ id: "s1", name: "Maya Patel" }],
  features: {
    cancellations: false, absence: false, invoices: false, reports: false, profile: false,
    booking: false, reschedule: false, classes: false, learning: false,
    guardian_invites: true, student_logins: true, documents: true,
  },
  welcome_text: "", help_url: "", terms_url: "",
}; // prettier-ignore

const BASE: Routes = {
  "GET /api/v1/me": { body: { membership: { role: "client" }, user: { email: "p@x.com" } } },
  "GET /api/v1/portal/me": { body: FAMILY_ME },
  "GET /api/v1/portal/dashboard": {
    body: { next_lesson: null, week: [], amount_due: [], latest_reports: [], news: [] },
  },
};

describe("household switcher (FR-15-1)", () => {
  it("switches the household the portal shows", async () => {
    const calls = mockApi({
      ...BASE,
      "POST /api/v1/portal/household": { body: { client_id: "c2" } },
    });
    render(<App />);
    const picker = await screen.findByLabelText("Household");
    fireEvent.change(picker, { target: { value: "c2" } });
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/v1/portal/household")?.body).toEqual({
        client_id: "c2",
      }),
    );
  });
});

describe("family page (FR-15-1, FR-15-8)", () => {
  it("invites another guardian and sets up a child's login", async () => {
    window.history.pushState(null, "", "/portal/family");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/portal/guardians": {
        body: [{ id: "g1", client_id: "c1", name: "Priya Patel", relationship: "parent",
                 portal: "active" }], // prettier-ignore
      },
      "POST /api/v1/portal/guardians": {
        status: 201,
        body: { id: "g2", client_id: "c1", name: "Raj Patel", relationship: "parent",
                portal: "invited" }, // prettier-ignore
      },
      "GET /api/v1/portal/student-logins": {
        body: [{ student_id: "s1", student_name: "Maya Patel", eligible: true,
                 has_email_login: false, username: "", pin_changed_at: null }], // prettier-ignore
      },
      "POST /api/v1/portal/student-logins": {
        status: 201,
        body: { student_id: "s1", student_name: "Maya Patel", eligible: true,
                has_email_login: false, username: "maya.p",
                pin_changed_at: "2026-10-14T10:00:00Z" }, // prettier-ignore
      },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Family and logins" })).toBeInTheDocument();
    expect(await screen.findByText("Priya Patel")).toBeInTheDocument();

    const invite = screen.getByRole("form", { name: "Invite another guardian" });
    fireEvent.change(screen.getByLabelText("First name"), { target: { value: "Raj" } });
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "raj@example.com" },
    });
    const send = screen.getByRole("button", { name: "Send invitation" });
    expect(send).toBeDisabled(); // must confirm parental responsibility first
    fireEvent.click(screen.getByLabelText(/They have parental responsibility/));
    fireEvent.submit(invite);
    expect(await screen.findByText(/Invitation sent/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/portal/guardians" && c.method === "POST")?.body)
      .toMatchObject({ first_name: "Raj", email: "raj@example.com", confirm: true }); // prettier-ignore

    fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "maya.p" } });
    fireEvent.change(screen.getByLabelText("PIN or password"), { target: { value: "482916" } });
    fireEvent.click(screen.getByLabelText(/I consent to them having a login/));
    fireEvent.click(screen.getByRole("button", { name: "Create login" }));
    await waitFor(
      () =>
      expect(calls.find((c) => c.path === "/api/v1/portal/student-logins" && c.method === "POST")
        ?.body).toEqual({ student_id: "s1", username: "maya.p", pin: "482916",
                          parental_consent: true }), // prettier-ignore
    );
  });
});

describe("documents to sign (FR-15-8)", () => {
  it("signs a document with a typed name", async () => {
    window.history.pushState(null, "", "/portal/documents");
    const calls = mockApi({
      ...BASE,
      "GET /api/v1/portal/documents": {
        body: [{ id: "d1", title: "Terms 2026", category: "contract", filename: "terms.pdf",
                 signature_required: true, signature_status: "awaiting", signed_at: null,
                 created_at: "2026-10-01T10:00:00Z" }], // prettier-ignore
      },
      "POST /api/v1/portal/documents/d1/sign": {
        status: 201,
        body: { signature_id: "sig1", signed_at: "2026-10-14T10:00:00Z", content_sha256: "ab" },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Sign Terms 2026" }));
    fireEvent.change(screen.getByLabelText("Your full name"), {
      target: { value: "Priya Patel" },
    });
    const sign = screen.getByRole("button", { name: "Sign" });
    expect(sign).toBeDisabled();
    fireEvent.click(screen.getByLabelText("I have read “Terms 2026” and agree to it."));
    fireEvent.click(sign);
    expect(await screen.findByText(/It's signed/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      full_name: "Priya Patel",
      agree: true,
    });
  });
});

describe("child sign-in (FR-15-1)", () => {
  it("signs a child in with a username and PIN", async () => {
    const calls = mockApi({
      "GET /api/v1/me": { status: 401, body: { type: "x", title: "Not signed in", status: 401 } },
      "POST /api/v1/auth/student-login": { status: 401, body: {
        type: "x", title: "Not signed in", status: 401,
        detail: "That username and PIN don't match." } }, // prettier-ignore
    });
    render(<App />);
    const form = await screen.findByRole("form", { name: "Child sign-in" });
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "maya.p" } });
    fireEvent.change(screen.getByLabelText("PIN or password"), { target: { value: "000001" } });
    fireEvent.submit(form);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That username and PIN don't match.",
    );
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      username: "maya.p",
      pin: "000001",
    });
  });
});
