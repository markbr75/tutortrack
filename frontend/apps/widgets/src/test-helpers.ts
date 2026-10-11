import { vi } from "vitest";

import { clearCache } from "./runtime";

export const BRAND = {
  name: "Bright Minds",
  logo_url: "",
  primary_colour: "#1d4ed8",
  on_primary: "#ffffff",
  link_colour: "#1d4ed8",
  secondary_colour: "#0f172a",
  font: "Inter",
  font_family: "'Inter', system-ui, sans-serif",
  font_css_url: "",
  show_powered_by: true,
  portal_url: "https://brightminds.tutortrack.app/portal/",
  login_url: "https://brightminds.tutortrack.app/login",
};

export interface Call {
  method: string;
  url: string;
  body: unknown;
}

/** Stub fetch: `{"GET branding": body}`; unmatched requests answer 404. */
export function mockFetch(
  routes: Record<string, unknown | ((body: unknown) => [number, unknown])>,
): Call[] {
  const calls: Call[] = [];
  clearCache();
  document.head.innerHTML =
    '<script data-org="brightminds" data-api="https://brightminds.tutortrack.app"></script>';
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      const path = url.replace("https://brightminds.tutortrack.app/api/v1/public/", "");
      const body: unknown = init.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url: path, body });
      const route = routes[`${method} ${path.split("?")[0]}`];
      let status = route === undefined ? 404 : 200;
      let payload = route;
      if (typeof route === "function")
        [status, payload] = (route as (b: unknown) => [number, unknown])(body);
      return new Response(JSON.stringify(payload ?? {}), { status });
    }),
  );
  return calls;
}

export async function settle(
  el: HTMLElement & { updateComplete: Promise<boolean> },
): Promise<void> {
  for (let i = 0; i < 6; i++) {
    await new Promise((r) => setTimeout(r, 0));
    await el.updateComplete;
  }
}
