import { applyBrandTheme, hexToHslTriplet } from "./brandTheme";

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
});
