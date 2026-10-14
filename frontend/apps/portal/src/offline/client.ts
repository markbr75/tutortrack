/**
 * The page side of the PWA (E16-T08): registers the service worker, queues changes made
 * without a signal, replays them when the connection returns (and asks the worker for a
 * Background Sync so they go even if the app is closed), and keeps the offline copy of the
 * tutor's next week fresh.
 */
import { readCookie, unwrap } from "@tutortrack/api-client";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, useSyncExternalStore } from "react";

import { api } from "../api";
import {
  clearOutbox,
  enqueue,
  flushOutbox,
  listOutbox,
  onOutboxChange,
  SYNC_TAG,
  type NewOutboxItem,
  type OutboxItem,
} from "./outbox";

const OWNER_KEY = "tt-offline-user";
const WARMED_KEY = "tt-offline-warmed";
const WARM_EVERY_MS = 30 * 60_000;

function storageGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // private mode: the offline copy just refreshes more often
  }
}

export function registerServiceWorker(): void {
  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/portal/sw.js", { scope: "/portal/" });
  });
}

function csrf(): string | null {
  const token = readCookie("csrftoken");
  return token ? decodeURIComponent(token) : null;
}

export function isOffline(): boolean {
  return typeof navigator !== "undefined" && navigator.onLine === false;
}

/** fetch() rejects with a TypeError when there's no connection (no HTTP response). */
export function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError;
}

export function flushNow() {
  return flushOutbox({ origin: window.location.origin, csrf });
}

async function requestBackgroundSync(): Promise<void> {
  if (!("serviceWorker" in navigator) || !navigator.serviceWorker.controller) return;
  const registration = (await navigator.serviceWorker.ready) as ServiceWorkerRegistration & {
    sync?: { register(tag: string): Promise<void> };
  };
  await registration.sync?.register(SYNC_TAG).catch(() => undefined);
}

/** Keep a change on this device until it can be sent. ``id`` is the Idempotency-Key the
 * first (failed) attempt used, so a request that did reach the server isn't repeated. */
export async function queueChange(
  item: Omit<NewOutboxItem, "csrf">,
  id?: string,
): Promise<OutboxItem> {
  const queued = await enqueue({ ...item, csrf: csrf() }, id);
  void requestBackgroundSync();
  return queued;
}

/** Replay on start-up and whenever the connection comes back. */
export function useOutboxSync(): void {
  useEffect(() => {
    const run = () => {
      if (!isOffline()) void flushNow();
    };
    run();
    window.addEventListener("online", run);
    return () => window.removeEventListener("online", run);
  }, []);
}

export function useOutbox(): OutboxItem[] {
  const [items, setItems] = useState<OutboxItem[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => void listOutbox().then((rows) => alive && setItems(rows));
    load();
    const off = onOutboxChange(load);
    return () => {
      alive = false;
      off();
    };
  }, []);
  return items;
}

function subscribeOnline(callback: () => void): () => void {
  window.addEventListener("online", callback);
  window.addEventListener("offline", callback);
  return () => {
    window.removeEventListener("online", callback);
    window.removeEventListener("offline", callback);
  };
}

export function useOnline(): boolean {
  return useSyncExternalStore(
    subscribeOnline,
    () => !isOffline(),
    () => true,
  );
}

/** Sign-out: no cached lessons, reports or queued changes stay on the device. */
export async function clearOfflineData(): Promise<void> {
  await clearOutbox();
  if (typeof caches !== "undefined") await caches.delete("tt-api").catch(() => false);
  navigator.serviceWorker?.controller?.postMessage({ type: "clear" });
  storageSet(WARMED_KEY, null);
  storageSet(OWNER_KEY, null);
}

/** A different person signed in on this device: drop the previous person's offline data. */
export function useOfflineOwner(userId: string | undefined): void {
  useEffect(() => {
    if (!userId) return;
    const previous = storageGet(OWNER_KEY);
    if (previous && previous !== userId) void clearOfflineData();
    storageSet(OWNER_KEY, userId);
  }, [userId]);
}

/** Keep the next 7 days on the phone (FR-16-3): the offline pack (report forms) and each
 * lesson's detail, read through the service worker, which caches them. At most every 30
 * minutes, and only once a worker controls the page. */
export function useWarmOfflineCache(enabled: boolean): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!enabled || isOffline() || !("serviceWorker" in navigator)) return;
    if (!navigator.serviceWorker.controller) return;
    if (Date.now() - Number(storageGet(WARMED_KEY) ?? 0) < WARM_EVERY_MS) return;
    let cancelled = false;
    void (async () => {
      try {
        const pack = unwrap(await api.GET("/api/v1/tutor/offline"));
        queryClient.setQueryData(["tutor", "offline"], pack);
        for (const lesson of pack.lessons) {
          if (cancelled) return;
          await api.GET("/api/v1/lessons/{id}", { params: { path: { id: lesson.id } } });
        }
        storageSet(WARMED_KEY, String(Date.now()));
      } catch {
        // try again next time the shell opens
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled, queryClient]);
}
