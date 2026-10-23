import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

type Routes = Parameters<typeof mockApi>[0];

const PERMS = {
  ...ME.permissions,
  "billing.invoice.view": "all",
  "billing.template.manage": "all",
  "people.client.view": "all",
  "people.client.edit": "all",
};

const STANDARD = {
  id: "tpl1",
  name: "Standard",
  is_default: true,
  style: "classic",
  accent_colour: "",
  logo_mode: "brand",
  logo: null,
  title: "",
  trading_name: "",
  intro: "",
  payment_instructions: "",
  footer: "",
  show_date: true,
  show_student: true,
  show_tutor: true,
  show_quantity: true,
  show_unit_price: true,
};
const MUSIC = {
  ...STANDARD,
  id: "tpl2",
  name: "Music lessons",
  is_default: false,
  style: "modern",
};

function base(extra: Routes = {}, permissions: Record<string, string> = PERMS): Routes {
  return {
    "GET /api/v1/me": { body: { ...ME, permissions } },
    "GET /api/v1/organisation": { body: { name: "Bright Minds", status: "active" } },
    "GET /api/v1/me/organisations": { body: [] },
    "GET /api/v1/public/branding": { body: { primary_colour: "#2a54a2" } },
    "GET /api/v1/invoice-templates": { body: [STANDARD, MUSIC] },
    "POST /api/v1/invoice-templates/preview": (body) => ({
      body: { html: `<p>preview ${String((body as { style?: string }).style)}</p>` },
    }),
    ...extra,
  };
}

describe("invoice templates", () => {
  it("lists the templates with the default marked", async () => {
    window.history.pushState(null, "", "/billing/templates");
    mockApi(base());
    render(<App />);
    expect(await screen.findByRole("link", { name: "Music lessons" })).toHaveAttribute(
      "href",
      "/billing/templates/tpl2",
    );
    expect(screen.getByText("Classic · Default")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New template" })).toHaveAttribute(
      "href",
      "/billing/templates/new",
    );
  });

  it("previews unsaved settings live and creates the template", async () => {
    window.history.pushState(null, "", "/billing/templates/new");
    const calls = mockApi(
      base({
        "POST /api/v1/invoice-templates": (body) => ({
          status: 201,
          body: { ...STANDARD, ...(body as object), id: "tpl3", is_default: false },
        }),
        "GET /api/v1/invoice-templates/tpl3": { body: { ...MUSIC, id: "tpl3" } },
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Music" } });
    fireEvent.click(screen.getByRole("button", { name: "Modern" }));
    expect(screen.getByRole("button", { name: "Modern" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.change(screen.getByLabelText("Trading name"), {
      target: { value: "Bright Minds Music" },
    });
    // A colour mid-typing is left out of the preview rather than refused.
    fireEvent.change(screen.getByLabelText("Accent colour"), { target: { value: "#7C3" } });
    fireEvent.click(screen.getByLabelText("Student"));
    const frame = await screen.findByTitle("Invoice preview", undefined, { timeout: 3000 });
    await waitFor(() => expect(frame.getAttribute("srcdoc")).toContain("preview modern"), {
      timeout: 3000,
    });
    expect(frame).toHaveAttribute("sandbox", "");
    const sent = calls.filter((c) => c.path === "/api/v1/invoice-templates/preview").at(-1);
    expect(sent?.body).toMatchObject({
      style: "modern",
      trading_name: "Bright Minds Music",
      accent_colour: "",
      show_student: false,
    });
    fireEvent.click(screen.getByRole("button", { name: "Create template" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.method === "POST" && c.path === "/api/v1/invoice-templates")?.body,
      ).toMatchObject({ name: "Music", style: "modern", accent_colour: "#7C3" }),
    );
    await waitFor(() => expect(window.location.pathname).toBe("/billing/templates/tpl3"));
  });

  it("shows the API's message beside the field", async () => {
    window.history.pushState(null, "", "/billing/templates/new");
    mockApi(
      base({
        "POST /api/v1/invoice-templates": {
          status: 422,
          body: {
            type: "about:blank",
            title: "Check the template",
            status: 422,
            errors: { accent_colour: ["Use a colour like #1D4ED8, or leave it empty."] },
          },
        },
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "X" } });
    fireEvent.click(screen.getByRole("button", { name: "Create template" }));
    expect(
      await screen.findByText("Use a colour like #1D4ED8, or leave it empty."),
    ).toBeInTheDocument();
  });

  it("deletes a template after confirming in place", async () => {
    window.history.pushState(null, "", "/billing/templates/tpl2");
    const calls = mockApi(
      base({
        "GET /api/v1/invoice-templates/tpl2": { body: MUSIC },
        "DELETE /api/v1/invoice-templates/tpl2": { status: 204, body: undefined },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete template" }));
    const confirm = screen.getByRole("group", { name: /Delete this template\?/ });
    fireEvent.click(within(confirm).getByRole("button", { name: "Delete template" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "DELETE" && c.path.endsWith("/tpl2"))).toBe(true),
    );
    await waitFor(() => expect(window.location.pathname).toBe("/billing/templates"));
  });

  it("is read-only without permission to manage templates", async () => {
    window.history.pushState(null, "", "/billing/templates/tpl1");
    const viewOnly = Object.fromEntries(
      Object.entries(PERMS).filter(([key]) => key !== "billing.template.manage"),
    );
    mockApi(base({ "GET /api/v1/invoice-templates/tpl1": { body: STANDARD } }, viewOnly));
    render(<App />);
    expect(await screen.findByLabelText("Name")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });

  it("lets a family choose its template", async () => {
    window.history.pushState(null, "", "/clients/c1");
    const client = {
      id: "c1",
      type: "household",
      display_name: "The Patel Family",
      status: "active",
      currency: "GBP",
      payment_terms_days: 14,
      po_number: "",
      invoice_template: null,
      billing_address: null,
      contacts: [],
      students: [],
    };
    const calls = mockApi(
      base({
        "GET /api/v1/clients/c1": { body: client },
        "GET /api/v1/notes": { body: { results: [], next: null } },
        "PATCH /api/v1/clients/c1": { body: { ...client, invoice_template: "tpl2" } },
      }),
    );
    render(<App />);
    expect(await screen.findByText("The organisation's default")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Edit billing details for The Patel Family" }),
    );
    fireEvent.change(screen.getByLabelText("Invoice template"), { target: { value: "tpl2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ invoice_template: "tpl2" }),
    );
  });
});
