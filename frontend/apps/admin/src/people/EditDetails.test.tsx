import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

const EDIT = {
  ...ME.permissions,
  "people.client.view": "all",
  "people.client.edit": "all",
  "people.student.view": "all",
  "people.student.edit": "all",
  "people.tutor.view": "all",
  "people.tutor.edit": "all",
};

function signedIn(permissions: Record<string, string>, routes: Record<string, unknown>) {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions } },
    "GET /api/v1/organisation": { body: { status: "active" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/notes": { body: { results: [], next: null } },
    ...routes,
  } as Parameters<typeof mockApi>[0];
}

const TUTOR = {
  id: "t1",
  first_name: "Nia",
  last_name: "Okafor",
  display_name: "",
  full_name: "Nia Okafor",
  email: "nia@example.com",
  phone: "",
  headline: "",
  bio_public: "",
  bio_private: "",
  travel_radius_km: null,
  delivers_online: true,
  delivers_in_person: false,
  status: "active",
  has_joined: true,
  subjects: [],
};

describe("editing a tutor's details", () => {
  it("saves only what changed and closes the form", async () => {
    window.history.pushState(null, "", "/tutors/t1");
    let tutor = TUTOR;
    const calls = mockApi(
      signedIn(EDIT, {
        "GET /api/v1/tutors/t1": () => ({ body: tutor }),
        "PATCH /api/v1/tutors/t1": (body: Record<string, unknown>) => {
          tutor = { ...tutor, ...body, full_name: `${String(body.first_name)} Okafor` };
          return { body: tutor };
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Nia Okafor's details" }));
    const form = screen.getByRole("form", { name: "Edit Nia Okafor's details" });
    // A tutor who has joined signs in with their email, so it isn't offered.
    expect(within(form).queryByLabelText("Email")).not.toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText("First name"), { target: { value: "Niamh" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
        first_name: "Niamh",
        invite: false,
      }),
    );
    expect(await screen.findByRole("heading", { name: "Niamh Okafor" })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: /details/ })).not.toBeInTheDocument();
  });

  it("offers the email for a tutor who hasn't joined, and shows the API's field errors", async () => {
    window.history.pushState(null, "", "/tutors/t1");
    mockApi(
      signedIn(EDIT, {
        "GET /api/v1/tutors/t1": { body: { ...TUTOR, has_joined: false } },
        "PATCH /api/v1/tutors/t1": {
          status: 422,
          body: {
            type: "validation",
            title: "Check the highlighted fields",
            status: 422,
            errors: { email: ["A tutor with this email already exists."] },
          },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Nia Okafor's details" }));
    const email = screen.getByLabelText("Email");
    fireEvent.change(email, { target: { value: "nia.new@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("A tutor with this email already exists.")).toBeInTheDocument();
  });

  it("isn't offered without permission to edit tutors", async () => {
    window.history.pushState(null, "", "/tutors/t1");
    mockApi(
      signedIn(
        Object.fromEntries(Object.entries(EDIT).filter(([key]) => key !== "people.tutor.edit")),
        { "GET /api/v1/tutors/t1": { body: TUTOR } },
      ),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Nia Okafor" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit Nia Okafor/ })).not.toBeInTheDocument();
  });
});

describe("editing a student's details", () => {
  it("saves the school and year group", async () => {
    window.history.pushState(null, "", "/students/s1");
    const calls = mockApi(
      signedIn(EDIT, {
        "GET /api/v1/students/s1": {
          body: {
            id: "s1",
            client: "c1",
            first_name: "Arjun",
            last_name: "Patel",
            preferred_name: "",
            full_name: "Arjun Patel",
            year_group: "Year 9",
            school: "",
            goals: "",
            status: "active",
            subjects: [],
          },
        },
        "PATCH /api/v1/students/s1": { body: { id: "s1" } },
        "GET /api/v1/jobs": { body: { results: [], next: null } },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Arjun Patel's details" }));
    fireEvent.change(screen.getByLabelText("Year group"), { target: { value: "Year 10" } });
    fireEvent.change(screen.getByLabelText("School"), { target: { value: "Hill Park" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
        year_group: "Year 10",
        school: "Hill Park",
      }),
    );
  });
});

describe("editing a family", () => {
  const CLIENT = {
    id: "c1",
    type: "household",
    display_name: "The Patel Family",
    status: "active",
    currency: "GBP",
    payment_terms_days: 14,
    po_number: "",
    billing_address: { line1: "1 High St", line2: "", city: "Leeds", postcode: "LS1 1AA" },
    contacts: [
      {
        id: "p1",
        first_name: "Priya",
        last_name: "Patel",
        full_name: "Priya Patel",
        relationship: "parent",
        email: "priya@example.com",
        phone: "",
        mobile: "",
        is_primary: true,
        is_bill_payer: true,
      },
    ],
    students: [],
  };

  it("sends the whole billing address when one line changes", async () => {
    window.history.pushState(null, "", "/clients/c1");
    const calls = mockApi(
      signedIn(EDIT, {
        "GET /api/v1/clients/c1": { body: CLIENT },
        "PATCH /api/v1/clients/c1": { body: CLIENT },
      }),
    );
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit billing details for The Patel Family" }),
    );
    fireEvent.change(screen.getByLabelText("Postcode"), { target: { value: "LS2 9JT" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
        billing_address_input: {
          line1: "1 High St",
          line2: "",
          city: "Leeds",
          postcode: "LS2 9JT",
          region: "",
          country: "",
        },
      }),
    );
  });

  it("edits a contact in place", async () => {
    window.history.pushState(null, "", "/clients/c1");
    const calls = mockApi(
      signedIn(EDIT, {
        "GET /api/v1/clients/c1": { body: CLIENT },
        "PATCH /api/v1/contacts/p1": { body: CLIENT.contacts[0] },
      }),
    );
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit Priya Patel's contact details" }),
    );
    const form = screen.getByRole("form", { name: "Edit Priya Patel's contact details" });
    fireEvent.change(within(form).getByLabelText("Mobile"), {
      target: { value: "07700 900456" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")).toMatchObject({
        path: "/api/v1/contacts/p1",
        body: { mobile: "07700 900456" },
      }),
    );
    // Back to the row, with focus on its Edit button.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Edit Priya Patel's contact details" }),
      ).toHaveFocus(),
    );
  });
});
