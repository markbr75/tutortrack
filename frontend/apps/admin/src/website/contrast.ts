/** WCAG 2.2 contrast helpers for the live theme preview (mirrors `sites.brand`). */

const HEX = /^#[0-9a-f]{6}$/i;
export const WHITE = "#ffffff";
export const DARK = "#111827";

export function isHex(value: string): boolean {
  return HEX.test(value);
}

function channel(v: number): number {
  const c = v / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const n = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16));
  return 0.2126 * channel(r!) + 0.7152 * channel(g!) + 0.0722 * channel(b!);
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return Math.round(((hi! + 0.05) / (lo! + 0.05)) * 100) / 100;
}

export function onColour(background: string): string {
  return contrast(background, WHITE) >= contrast(background, DARK) ? WHITE : DARK;
}

function shade(hex: string, factor: number): string {
  const n = hex.replace("#", "");
  return (
    "#" +
    [0, 2, 4]
      .map((i) => Math.max(0, Math.min(255, Math.round(parseInt(n.slice(i, i + 2), 16) * factor))))
      .map((v) => v.toString(16).padStart(2, "0"))
      .join("")
  );
}

/** The colour darkened just enough for 4.5:1 on white (links and headings). */
export function readableOnWhite(colour: string): string {
  let current = colour.toLowerCase();
  for (let i = 0; i < 40; i++) {
    if (contrast(current, WHITE) >= 4.5) return current;
    current = shade(current, 0.92);
  }
  return DARK;
}
