import { readCookieConsent, writeCookieConsent } from "@tutortrack/ui";

import { api } from "../api";

/**
 * First-party product analytics (E30 FR-30-6). Nothing is queued or sent unless the person
 * chose "analytics" (cookie banner or help panel) *and* the organisation allows it
 * (`analytics_allowed` from `/me/guidance`). Routes are sent as patterns (ids replaced)
 * and properties must be short, non-identifying values; the server filters again.
 */
export interface UsageEvent {
  name: string;
  route?: string;
  properties?: Record<string, string | number | boolean | null>;
  occurred_at?: string;
}

let allowedByOrganisation = false;
let queue: UsageEvent[] = [];
let timer: ReturnType<typeof setTimeout> | undefined;
const FLUSH_MS = 5_000;
const MAX_QUEUE = 50;

export function setOrganisationAllowsAnalytics(allowed: boolean) {
  allowedByOrganisation = allowed;
  if (!allowed) queue = [];
}

export function analyticsConsented(): boolean {
  return readCookieConsent()?.analytics === true;
}

/** The person's own choice; keeps their marketing choice as it was. */
export function setAnalyticsConsent(on: boolean) {
  const current = readCookieConsent();
  writeCookieConsent({ analytics: on, marketing: current?.marketing ?? false });
  if (!on) queue = [];
}

const ID_SEGMENT = /^(\d+|[0-9a-f-]{16,}|[A-Za-z0-9_-]{24,})$/i;

export function routePattern(pathname: string): string {
  const parts = pathname
    .split(/[?#]/)[0]!
    .split("/")
    .filter(Boolean)
    .map((part) => (ID_SEGMENT.test(part) || part.includes("@") ? "$id" : part.toLowerCase()));
  return `/${parts.join("/")}`;
}

export function track(name: string, properties?: UsageEvent["properties"], route?: string) {
  if (!allowedByOrganisation || !analyticsConsented()) return;
  queue.push({
    name,
    route: route ?? routePattern(window.location.pathname),
    properties,
    occurred_at: new Date().toISOString(),
  });
  if (queue.length >= MAX_QUEUE) void flush();
  else if (!timer) timer = setTimeout(() => void flush(), FLUSH_MS);
}

export async function flush() {
  if (timer) clearTimeout(timer);
  timer = undefined;
  const events = queue.splice(0, MAX_QUEUE);
  if (events.length === 0 || !analyticsConsented()) return;
  try {
    await api.POST("/api/v1/analytics/events", { body: { events } });
  } catch {
    // Usage data is best effort: never bother the person with it.
  }
}
