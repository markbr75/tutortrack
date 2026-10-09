import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

describe("SignupPage", () => {
  it("creates the account and continues on the new organisation", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, pathname: "/signup", search: "" });
    window.history.pushState(null, "", "/signup");
    const calls = mockApi({
      "GET /api/v1/signup/config": { body: { turnstile_site_key: "" } },
      "POST /api/v1/signup": {
        status: 201,
        body: { continue_url: "https://sam.tutortrack.app/onboarding?handoff=abc" },
      },
    });
    render(<App />);

    fireEvent.change(await screen.findByLabelText("First name"), { target: { value: "Sam" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "sam@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long-pass-123" } });
    fireEvent.change(screen.getByLabelText("Business name"), { target: { value: "Sam Tutoring" } });
    fireEvent.change(screen.getByLabelText("Type of business"), { target: { value: "agency" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://sam.tutortrack.app/onboarding?handoff=abc"),
    );
    const sent = calls.find((c) => c.path === "/api/v1/signup")?.body as Record<string, string>;
    expect(sent).toMatchObject({
      first_name: "Sam",
      email: "sam@example.com",
      business_name: "Sam Tutoring",
      business_type: "agency",
      country: "GB",
    });
  });

  it("shows field errors from the API next to the field", async () => {
    window.history.pushState(null, "", "/signup");
    mockApi({
      "GET /api/v1/signup/config": { body: { turnstile_site_key: "" } },
      "POST /api/v1/signup": {
        status: 422,
        body: {
          type: "signup-rejected",
          title: "Signup could not be completed",
          status: 422,
          errors: { email: ["An account with this email already exists."] },
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Create account" }));
    const email = screen.getByLabelText("Email");
    expect(await screen.findByText("An account with this email already exists.")).toBeVisible();
    expect(email).toHaveAttribute("aria-invalid", "true");
  });
});
