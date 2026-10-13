/**
 * What the portal's service worker caches (E16-T08). Shared by the worker and its tests;
 * no `window` or `document` here.
 *
 * - The app shell (HTML, hashed JS/CSS, icons) for everyone, so the portal opens offline.
 * - Tutor data only (Today, the offline pack, lessons, reports, the calendar), so the tutor
 *   flows work offline. Family pages stay online-only: their API reads are never cached.
 */

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";

const OFFLINE_API = new RegExp(
  "^/api/v1/(" +
    [
      "me",
      "tutor/[a-z-]+",
      `lessons/${UUID}`,
      `lessons/${UUID}/(reports|join)`,
      `lesson-reports/${UUID}`,
      "calendar",
      "public/(branding|manifest)",
      "push-subscriptions/config",
    ].join("|") +
    ")$",
);

/** API reads served from the cache when there's no network. */
export function isOfflineApi(pathname: string): boolean {
  return OFFLINE_API.test(pathname);
}

/** Reads whose query changes daily (date ranges): offline, any cached copy will do. */
export function matchesIgnoringQuery(pathname: string): boolean {
  return pathname === "/api/v1/calendar";
}

/** Hashed build output and icons: never change, cache first. */
export function isStaticAsset(pathname: string): boolean {
  return pathname.startsWith("/portal/assets/") || pathname.startsWith("/portal/icons/");
}

/** Where a push notification may open: a path on this site, inside the portal or app. */
export function notificationTarget(url: unknown): string {
  if (typeof url !== "string" || !url.startsWith("/") || url.startsWith("//")) {
    return "/portal/";
  }
  return url;
}

export interface PushPayload {
  title: string;
  body: string;
  url: string;
  tag: string;
}

export function parsePush(data: unknown): PushPayload {
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    title: typeof raw.title === "string" && raw.title ? raw.title : "TutorTrack",
    body: typeof raw.body === "string" ? raw.body : "",
    url: notificationTarget(raw.url),
    tag: typeof raw.tag === "string" ? raw.tag : "",
  };
}
