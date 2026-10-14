import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "./App";
import { ME, mockApi } from "./test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const PERMS = {
  ...ME.permissions,
  "people.client.view": "all",
  "crm.note.view": "all",
  "crm.document.view": "all",
  "crm.document.create": "all",
};

const base = {
  "GET /api/v1/me": { body: { ...ME, permissions: PERMS } },
  "GET /api/v1/organisation": { body: { status: "active" } },
  "GET /api/v1/me/organisations": { body: [] },
};

const CLIENT = {
  id: "c1", type: "household", display_name: "The Patel Family", status: "active",
  currency: "GBP", payment_terms_days: 14, students_count: 0, billing_address: null,
  contacts: [], students: [],
}; // prettier-ignore

const DOC = {
  id: "d1", target_type: "people.client", target_id: "c1", file: "f1", filename: "terms.pdf",
  title: "Terms 2026", category: "contract", visibility: "shared_with_client",
  expires_on: null, signature_required: true, signature_status: "signed",
  signed_at: "2026-10-14T10:00:00Z", created_by: null, created_at: "2026-10-01T10:00:00Z",
}; // prettier-ignore

describe("change email (FR-03-9)", () => {
  it("asks for a link to the new address", async () => {
    window.history.pushState(null, "", "/account");
    const calls = mockApi({
      ...base,
      "GET /api/v1/me/sessions": { body: [] },
      "POST /api/v1/me/email": { status: 202, body: { pending_email: "new@example.com" } },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("New email address"), {
      target: { value: "new@example.com" },
    });
    const section = screen.getByRole("region", { name: "Email address" });
    fireEvent.change(within(section).getByLabelText("Current password"), {
      target: { value: "pw" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change email" }));
    expect(await screen.findByText(/We've sent a link to new@example.com/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/me/email")?.body).toEqual({
      new_email: "new@example.com",
      password: "pw",
    });
  });

  it("confirms the new address from the emailed link", async () => {
    window.history.pushState(null, "", "/confirm-email?token=abc");
    const calls = mockApi({
      ...base,
      "POST /api/v1/auth/email-change/confirm": { body: { email: "new@example.com" } },
    });
    render(<App />);
    expect(
      await screen.findByText(/Your email address is now new@example.com/),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ token: "abc" });
  });
});

describe("documents and signatures (FR-05-9)", () => {
  it("shows a signed document's audit trail", async () => {
    window.history.pushState(null, "", "/clients/c1");
    mockApi({
      ...base,
      "GET /api/v1/clients/c1": { body: CLIENT },
      "GET /api/v1/notes": { body: { results: [], next: null } },
      "GET /api/v1/documents": { body: { results: [DOC], next: null } },
      "GET /api/v1/documents/d1/signatures": {
        body: [{ id: "sig1", kind: "document", document: "d1", tutor: null, agreement_key: "",
                 title: "Terms 2026", statement: "I agree", signer: "u2",
                 signer_name: "Priya Patel", signer_email: "p@example.com", signer_role: "client",
                 signed_at: "2026-10-14T10:00:00Z", ip: "203.0.113.5", user_agent: "Firefox",
                 content_sha256: "abc123", signed_file: "f2" }], // prettier-ignore
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Documents" }));
    expect(await screen.findByText("Terms 2026")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Signature details" }));
    expect(await screen.findByText(/Signed by Priya Patel/)).toBeInTheDocument();
    expect(screen.getByText(/203.0.113.5/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download the signed copy" })).toBeInTheDocument();
  });

  it("asks a family to sign a document", async () => {
    window.history.pushState(null, "", "/clients/c1");
    const calls = mockApi({
      ...base,
      "GET /api/v1/clients/c1": { body: CLIENT },
      "GET /api/v1/notes": { body: { results: [], next: null } },
      "GET /api/v1/documents": {
        body: { results: [{ ...DOC, signature_required: false, signature_status: "not_required",
                            signed_at: null }], next: null }, // prettier-ignore
      },
      "POST /api/v1/documents/d1/request-signature": {
        body: { ...DOC, signature_status: "awaiting", signed_at: null },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "Documents" }));
    fireEvent.click(await screen.findByRole("button", { name: "Ask for a signature" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/request-signature"))?.body).toEqual({
        signature_required: true,
      }),
    );
  });
});
