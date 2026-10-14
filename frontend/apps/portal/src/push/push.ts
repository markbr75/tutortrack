/** Web Push in the browser (E16-T09): subscribe this device with the organisation's VAPID
 * key and register it with the API; iOS needs the app on the Home Screen first (16.4+). */
import { unwrap } from "@tutortrack/api-client";

import { api } from "../api";

const SUBSCRIPTION_KEY = "tt-push-subscription";

export function pushSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export function isIos(): boolean {
  const ua = navigator.userAgent;
  return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}

export function isStandalone(): boolean {
  const legacy = (navigator as Navigator & { standalone?: boolean }).standalone;
  return Boolean(legacy) || window.matchMedia?.("(display-mode: standalone)").matches === true;
}

/** A name the tutor recognises in their device list (no fingerprinting detail). */
export function deviceName(): string {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return "iPhone";
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "iPad";
  if (/Android/.test(ua)) return "Android";
  if (/Windows/.test(ua)) return "Windows";
  if (/Macintosh/.test(ua)) return "Mac";
  if (/Linux/.test(ua)) return "Linux";
  return "Browser";
}

export function vapidKeyBytes(base64url: string): Uint8Array {
  const padded = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4))
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  const raw = atob(padded);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const registration = await navigator.serviceWorker.getRegistration("/portal/");
  return (await registration?.pushManager.getSubscription()) ?? null;
}

function remember(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(SUBSCRIPTION_KEY, id);
    else window.localStorage.removeItem(SUBSCRIPTION_KEY);
  } catch {
    // private mode
  }
}

export function rememberedSubscriptionId(): string | null {
  try {
    return window.localStorage.getItem(SUBSCRIPTION_KEY);
  } catch {
    return null;
  }
}

/** Ask permission (must follow a tap), subscribe and register this device. */
export async function enablePush(vapidPublicKey: string): Promise<"on" | "denied"> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return "denied";
  const registration = await navigator.serviceWorker.ready;
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: vapidKeyBytes(vapidPublicKey),
    }));
  const json = subscription.toJSON();
  const saved = unwrap(
    await api.POST("/api/v1/push-subscriptions", {
      body: {
        endpoint: json.endpoint ?? subscription.endpoint,
        keys: { p256dh: json.keys?.p256dh ?? "", auth: json.keys?.auth ?? "" },
        device: deviceName(),
      },
    }),
  );
  remember(saved.id);
  return "on";
}

/** Stop pushes to this device: unsubscribe the browser and forget it on the server. */
export async function disablePush(): Promise<void> {
  const subscription = await currentSubscription();
  await subscription?.unsubscribe();
  const id = rememberedSubscriptionId();
  if (id) {
    await api.DELETE("/api/v1/push-subscriptions/{id}", { params: { path: { id } } });
  }
  remember(null);
}
