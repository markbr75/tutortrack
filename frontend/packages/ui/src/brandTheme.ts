/**
 * Runtime tenant theming (E24 FR-24-1): maps the organisation's brand onto the design
 * tokens in styles.css. Colours come from `/api/v1/public/branding`, whose `on_primary` is
 * already the AA-safe text colour for the brand colour.
 */

export interface BrandTheme {
  primary_colour: string;
  on_primary: string;
  font_family?: string;
  font_css_url?: string;
  favicon_url?: string;
}

/** "#1d4ed8" → "224 76% 48%" (the token format). */
export function hexToHslTriplet(hex: string): string | null {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return null;
  const n = parseInt(m[1]!, 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => v / 255) as [
    number,
    number,
    number,
  ];
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  let h = 0;
  let s = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h *= 60;
  }
  return `${Math.round(h)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
}

/** Apply the brand; `full` also sets the font and favicon (portals and public pages). */
export function applyBrandTheme(
  brand: BrandTheme,
  { full = false, root = document.documentElement }: { full?: boolean; root?: HTMLElement } = {},
): void {
  const primary = hexToHslTriplet(brand.primary_colour);
  const on = hexToHslTriplet(brand.on_primary);
  if (primary && on) {
    root.style.setProperty("--tt-brand", primary);
    root.style.setProperty("--tt-brand-foreground", on);
  }
  if (!full) return;
  if (brand.font_family) root.style.setProperty("font-family", brand.font_family);
  if (brand.font_css_url && !document.querySelector(`link[href="${brand.font_css_url}"]`)) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = brand.font_css_url;
    document.head.append(link);
  }
  if (brand.favicon_url) {
    let icon = document.querySelector<HTMLLinkElement>("link[rel=icon]");
    if (!icon) {
      icon = document.createElement("link");
      icon.rel = "icon";
      document.head.append(icon);
    }
    icon.href = brand.favicon_url;
  }
}
