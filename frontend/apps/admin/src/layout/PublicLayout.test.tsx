import { render, screen } from "@testing-library/react";

import { App } from "../App";
import { mockApi } from "../test-utils";

const BRANDING = {
  name: "Bright Minds", logo_url: "", logo_dark_url: "", favicon_url: "/media/bm.ico",
  app_icon_url: "", app_name: "", primary_colour: "#1d4ed8", on_primary: "#ffffff",
  link_colour: "", secondary_colour: "", font: "lato", font_family: "'Lato', sans-serif",
  font_css_url: "", social_links: {}, show_powered_by: true, portal_url: "", login_url: "",
}; // prettier-ignore

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

describe("public pages", () => {
  it("show the tenant's favicon but keep Source Sans", async () => {
    document.head.innerHTML = "";
    window.history.pushState(null, "", "/login");
    mockApi({ "GET /api/v1/public/branding": { body: BRANDING } });
    const { unmount } = render(<App />);
    expect(await screen.findByText("Bright Minds")).toBeInTheDocument();
    expect(document.querySelector("link[rel~=icon]")?.getAttribute("href")).toBe("/media/bm.ico");
    expect(document.documentElement.style.getPropertyValue("--tt-brand")).toBe("224 76% 48%");
    expect(document.documentElement.style.getPropertyValue("font-family")).toBe("");
    // Leaving the tenant's page hands the tab back to TutorTrack's icon.
    unmount();
    expect(document.querySelector("link[rel~=icon]")).toBeNull();
  });
});
