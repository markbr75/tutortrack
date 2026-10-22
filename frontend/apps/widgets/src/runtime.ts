/**
 * Widget runtime (E24 FR-24-3): finds the organisation and API from the loader script
 * (`<script type="module" src=".../widgets.js" data-org="slug" data-api="https://...">`),
 * fetches public data (anonymous, CORS-limited to the organisation's sites), applies the
 * brand as CSS custom properties and emits analytics events (`tt:enquiry_submitted`...) on
 * window, also forwarded to GA4 (`gtag`), GTM (`dataLayer`) and the Meta pixel (`fbq`).
 */

export interface Branding {
  name: string;
  logo_url: string;
  primary_colour: string;
  on_primary: string;
  link_colour: string;
  secondary_colour: string;
  font: string;
  font_family: string;
  font_css_url: string;
  show_powered_by: boolean;
  portal_url: string;
  login_url: string;
}

export interface WidgetConfig {
  key: string;
  kind: string;
  element: string;
  options: Record<string, unknown>;
  theme: Record<string, string>;
  branding: Branding;
}

function loader(): HTMLScriptElement | null {
  return document.querySelector<HTMLScriptElement>("script[data-org]");
}

/** API origin: `data-api`, else the organisation's TutorTrack address, else this page. */
export function apiBase(): string {
  const script = loader();
  const api = script?.dataset.api;
  if (api) return api.replace(/\/$/, "");
  const org = script?.dataset.org;
  if (org && api === undefined) return `https://${org}.tutortrack.app`;
  return "";
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(`HTTP ${status}`);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase()}/api/v1/public/${path}`, {
    ...init,
    credentials: "omit",
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body);
  return body as T;
}

const cache = new Map<string, Promise<unknown>>();

/** GETs are shared between widgets on the page. */
export function cached<T>(path: string): Promise<T> {
  if (!cache.has(path)) {
    const request = api<T>(path);
    request.catch(() => cache.delete(path));
    cache.set(path, request);
  }
  return cache.get(path) as Promise<T>;
}

export function clearCache(): void {
  cache.clear();
}

export function branding(): Promise<Branding> {
  return cached<Branding>("branding");
}

export function widgetConfig(key: string): Promise<WidgetConfig> {
  return cached<WidgetConfig>(`widgets/${encodeURIComponent(key)}`);
}

const ALLOWED_THEME = /^--tt-[a-z-]+$/;

/** Brand colours and font as CSS custom properties on the widget host. */
export function applyTheme(
  host: HTMLElement,
  brand: Branding | undefined,
  theme: Record<string, string> = {},
): void {
  if (brand) {
    host.style.setProperty("--tt-brand-color", brand.primary_colour);
    host.style.setProperty("--tt-on-brand", brand.on_primary);
    host.style.setProperty("--tt-link-color", brand.link_colour);
  }
  // Only a font the tenant chose (`font` is empty otherwise, while `font_family` still carries
  // a system stack): without one the widget keeps the host page's own font.
  if (brand?.font && brand.font_family) {
    host.style.setProperty("--tt-font", brand.font_family);
    if (brand.font_css_url && !document.querySelector(`link[href="${brand.font_css_url}"]`)) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = brand.font_css_url;
      document.head.append(link);
    }
  }
  for (const [name, value] of Object.entries(theme)) {
    if (ALLOWED_THEME.test(name)) host.style.setProperty(name, value);
  }
}

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
    fbq?: (...args: unknown[]) => void;
  }
}

/** Analytics hook: `tt:<name>` on window, plus GA4/GTM/Meta pixel when present. */
export function emit(name: string, detail: Record<string, unknown> = {}): void {
  window.dispatchEvent(new CustomEvent(`tt:${name}`, { detail }));
  window.dataLayer?.push({ event: `tt_${name}`, ...detail });
  if (name === "enquiry_submitted") {
    window.gtag?.("event", "generate_lead", detail);
    window.fbq?.("track", "Lead", detail);
  }
}
