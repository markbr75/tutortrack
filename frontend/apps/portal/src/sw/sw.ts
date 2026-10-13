/// <reference lib="webworker" />
/**
 * The portal's service worker (E16-T08/T09), built to /portal/sw.js by the Vite plugin in
 * vite.config.ts, which injects the precache list and a version.
 *
 * - Precaches the app shell; navigations are network-first with the cached shell offline.
 * - Tutor API reads (routes.ts) are network-first with a cached copy offline; family data
 *   is never cached.
 * - Background Sync replays the offline outbox (outbox.ts) when the connection is back,
 *   even with the app closed.
 * - Shows Web Push notifications and opens their link.
 */
import {
  clearOutbox,
  flushOutbox,
  listOutbox,
  SYNC_TAG,
  type FlushResult,
} from "../offline/outbox";
import {
  isOfflineApi,
  isStaticAsset,
  matchesIgnoringQuery,
  notificationTarget,
  parsePush,
} from "../offline/routes";

declare const self: ServiceWorkerGlobalScope;
declare const __PRECACHE__: string[];
declare const __SW_VERSION__: string;

const SHELL = `tt-shell-${__SW_VERSION__}`;
const API = "tt-api";
const INDEX = "/portal/index.html";
const NETWORK_TIMEOUT_MS = 4000;

interface SyncEvent extends ExtendableEvent {
  readonly tag: string;
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL)
      .then((cache) => cache.addAll(__PRECACHE__))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((k) => k.startsWith("tt-shell-") && k !== SHELL).map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

function withTimeout(request: Request): Promise<Response> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("timeout")), NETWORK_TIMEOUT_MS);
    fetch(request).then(
      (response) => {
        clearTimeout(timer);
        resolve(response);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error instanceof Error ? error : new Error("network"));
      },
    );
  });
}

function offlineProblem(): Response {
  const body = {
    type: "https://docs.tutortrack.app/problems/offline",
    title: "Offline",
    status: 503,
    detail: "You're offline and this hasn't been saved on this device.",
  };
  return new Response(JSON.stringify(body), {
    status: 503,
    headers: { "Content-Type": "application/problem+json" },
  });
}

async function apiRead(request: Request, pathname: string): Promise<Response> {
  const cache = await caches.open(API);
  try {
    const response = await withTimeout(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch {
    const cached =
      (await cache.match(request)) ??
      (matchesIgnoringQuery(pathname)
        ? await cache.match(request, { ignoreSearch: true })
        : undefined);
    return cached ?? offlineProblem();
  }
}

async function navigation(request: Request): Promise<Response> {
  try {
    return await withTimeout(request);
  } catch {
    return (await caches.match(INDEX)) ?? Response.error();
  }
}

async function staticAsset(request: Request): Promise<Response> {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) (await caches.open(SHELL)).put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (request.mode === "navigate" && url.pathname.startsWith("/portal")) {
    event.respondWith(navigation(request));
  } else if (isStaticAsset(url.pathname)) {
    event.respondWith(staticAsset(request));
  } else if (isOfflineApi(url.pathname)) {
    event.respondWith(apiRead(request, url.pathname));
  }
});

async function sync(): Promise<FlushResult> {
  const result = await flushOutbox({ origin: self.location.origin });
  const waiting = await listOutbox();
  if (waiting.some((item) => item.state === "pending")) {
    throw new Error("still offline"); // the browser retries the sync later
  }
  return result;
}

self.addEventListener("sync", (event) => {
  const syncEvent = event as SyncEvent;
  if (syncEvent.tag === SYNC_TAG) syncEvent.waitUntil(sync());
});

self.addEventListener("message", (event) => {
  const type = (event.data as { type?: string } | null)?.type;
  if (type === "flush") {
    event.waitUntil(flushOutbox({ origin: self.location.origin }));
  } else if (type === "clear") {
    // Signed out (or another person signed in): drop their cached data and queue.
    event.waitUntil(Promise.all([caches.delete(API), clearOutbox()]));
  }
});

self.addEventListener("push", (event) => {
  let data: unknown = null;
  try {
    data = event.data?.json();
  } catch {
    data = { body: event.data?.text() };
  }
  const push = parsePush(data);
  event.waitUntil(
    self.registration.showNotification(push.title, {
      body: push.body,
      tag: push.tag || undefined,
      icon: "/portal/icons/icon-192.png",
      badge: "/portal/icons/icon-192.png",
      data: { url: push.url },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = notificationTarget((event.notification.data as { url?: unknown })?.url);
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => new URL(w.url).pathname.startsWith("/portal"));
      if (open) return open.focus().then((w) => w.navigate(target));
      return self.clients.openWindow(target);
    }),
  );
});
