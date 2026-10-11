import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/portal/");
  document.documentElement.removeAttribute("style");
});

const PROFILE = {
  id: "pp1",
  tutor: "t1",
  tutor_name: "Nia Adeyemi",
  slug: "nia-a",
  status: "draft",
  listed: false,
  draft: { display_name: "Nia A.", headline: "", bio: "", show: ["qualifications"] },
  published: { display_name: "", headline: "", bio: "", show: [] },
  photo: null,
  draft_photo: null,
  submitted_at: null,
  approved_at: null,
  approved_by_name: "",
  rejection_reason: "",
  updated_at: "2026-10-10T10:00:00Z",
};

const BRAND = {
  name: "Bright Minds",
  logo_url: "",
  logo_dark_url: "",
  favicon_url: "",
  app_icon_url: "",
  app_name: "Bright Minds",
  primary_colour: "#1d4ed8",
  on_primary: "#ffffff",
  link_colour: "#1d4ed8",
  secondary_colour: "#0f172a",
  font: "",
  font_family: "system-ui",
  font_css_url: "",
  social_links: {},
  show_powered_by: true,
  portal_url: "https://brightminds.tutortrack.app/portal/",
  login_url: "https://brightminds.tutortrack.app/login",
};

describe("tutor public profile and portal branding", () => {
  it("submits profile edits for approval and shows field errors", async () => {
    window.history.pushState(null, "", "/portal/tutor/profile");
    let attempt = 0;
    const calls = mockApi({
      "GET /api/v1/me": {
        body: { membership: { role: "tutor" }, user: { email: "nia@example.com" } },
      },
      "GET /api/v1/tutor/me": {
        body: {
          id: "t1",
          name: "Nia Adeyemi",
          email: "nia@example.com",
          can_cancel: true,
          can_edit_lessons: false,
          can_see_pay: false,
        },
      },
      "GET /api/v1/tutors/t1": { body: { id: "t1", headline: "", bio_public: "", phone: "" } },
      "GET /api/v1/me/pay-profile": { body: {} },
      "GET /api/v1/public/branding": { body: BRAND },
      "GET /api/v1/public-profiles/mine": { body: PROFILE },
      "PUT /api/v1/public-profiles/mine": () => {
        attempt += 1;
        return attempt === 1
          ? {
              status: 422,
              body: {
                type: "x/business-rule",
                title: "No",
                status: 422,
                errors: { bio: ["Phone numbers aren't allowed in public profiles."] },
              },
            }
          : { body: { ...PROFILE, status: "pending" } };
      },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Public profile" })).toBeInTheDocument();
    expect(screen.getByText("Not submitted yet")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("About me"), { target: { value: "Call 07700 900123" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and submit" }));
    expect(await screen.findByText(/Phone numbers aren't allowed/)).toBeInTheDocument();
    expect(screen.getByLabelText("About me")).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(screen.getByLabelText("About me"), { target: { value: "Maths for all." } });
    fireEvent.click(screen.getByRole("button", { name: "Save and submit" }));
    expect(
      await screen.findByText("Saved. Your changes will show once approved."),
    ).toBeInTheDocument();
    const put = calls.filter((c) => c.method === "PUT").pop()?.body;
    expect(put).toMatchObject({
      display_name: "Nia A.",
      bio: "Maths for all.",
      show: ["qualifications"],
    });
    // Portal branding: brand tokens and the powered-by footer.
    await waitFor(() =>
      expect(document.documentElement.style.getPropertyValue("--tt-brand")).toBe("224 76% 48%"),
    );
    expect(screen.getByText("TutorTrack")).toBeInTheDocument();
  });
});
