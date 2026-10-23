import { applyBrandFavicon, applyBrandTheme, hexToHslTriplet } from "./brandTheme";

describe("brand theme", () => {
  it("converts hex to the token format", () => {
    expect(hexToHslTriplet("#ffffff")).toBe("0 0% 100%");
    expect(hexToHslTriplet("#1d4ed8")).toBe("224 76% 48%");
    expect(hexToHslTriplet("blue")).toBeNull();
  });

  it("sets tokens, and the font and favicon in full mode", () => {
    const root = document.createElement("div");
    applyBrandTheme(
      {
        primary_colour: "#fde047",
        on_primary: "#111827",
        font_family: "'Lato'",
        favicon_url: "/f.png",
      },
      { full: true, root },
    );
    expect(root.style.getPropertyValue("--tt-brand")).toBe("50 98% 64%");
    expect(root.style.getPropertyValue("--tt-brand-foreground")).toBe("221 39% 11%");
    expect(root.style.getPropertyValue("font-family")).toContain("Lato");
    expect(document.querySelector<HTMLLinkElement>("link[rel=icon]")?.getAttribute("href")).toBe(
      "/f.png",
    );
  });

  it("sets the favicon alone on request, never the font", () => {
    document.head.innerHTML = "";
    const root = document.createElement("div");
    applyBrandTheme(
      {
        primary_colour: "#1d4ed8",
        on_primary: "#ffffff",
        font_family: "'Lato'",
        favicon_url: "/t.ico",
      },
      { favicon: true, root },
    );
    expect(root.style.getPropertyValue("--tt-brand")).toBe("224 76% 48%");
    expect(root.style.getPropertyValue("font-family")).toBe("");
    expect(document.querySelector("link[rel~=icon]")?.getAttribute("href")).toBe("/t.ico");
  });

  it("leaves the favicon alone by default", () => {
    document.head.innerHTML = '<link rel="icon" href="/tutortrack.png" />';
    applyBrandTheme(
      { primary_colour: "#1d4ed8", on_primary: "#ffffff", favicon_url: "/t.ico" },
      { root: document.createElement("div") },
    );
    expect(document.querySelector("link[rel~=icon]")?.getAttribute("href")).toBe("/tutortrack.png");
  });

  it("puts TutorTrack's favicon back when a page hands back", () => {
    document.head.innerHTML = '<link rel="icon" type="image/png" href="/tutortrack.png" />';
    const restore = applyBrandFavicon("/tenant.svg");
    const icon = document.querySelector("link[rel~=icon]")!;
    expect(icon.getAttribute("href")).toBe("/tenant.svg");
    expect(icon.hasAttribute("type")).toBe(false);
    restore();
    expect(icon.getAttribute("href")).toBe("/tutortrack.png");
    expect(icon.getAttribute("type")).toBe("image/png");

    document.head.innerHTML = "";
    const undo = applyBrandFavicon("/tenant.svg");
    expect(document.querySelectorAll("link[rel~=icon]")).toHaveLength(1);
    undo();
    expect(document.querySelector("link[rel~=icon]")).toBeNull();
  });
});
