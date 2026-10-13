import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { App } from "../App";
import { resetMemoryStorage } from "../offline/outbox";
import { mockApi } from "../test-utils";

type Routes = Parameters<typeof mockApi>[0];

const KEY =
  "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U";

function routes(extra: Routes = {}): Routes {
  return {
    "GET /api/v1/me": {
      body: { membership: { role: "tutor" }, user: { id: "u1", email: "nia@example.com" } },
    },
    "GET /api/v1/tutor/me": {
      body: {
        id: "t1",
        name: "Nia Adeyemi",
        email: "nia@example.com",
        can_cancel: false,
        can_edit_lessons: false,
        can_see_pay: true,
      },
    },
    "GET /api/v1/push-subscriptions/config": { body: { enabled: true, vapid_public_key: KEY } },
    "GET /api/v1/push-subscriptions": {
      body: {
        next: null,
        previous: null,
        results: [
          {
            id: "s1",
            device: "Android",
            push_service: "fcm.googleapis.com",
            last_sent_at: null,
            created_at: "2026-10-01T09:00:00Z",
          },
        ],
      },
    },
    "GET /api/v1/communication-preferences/mine": {
      body: {
        preferences: [
          {
            category: "scheduling",
            available: ["email", "sms", "in_app", "push"],
            channels: ["email", "sms", "in_app", "push"],
          },
          { category: "billing", available: ["email", "in_app", "push"], channels: ["in_app"] },
        ],
      },
    },
    ...extra,
  };
}

/** A browser with Push: permission, a service worker registration and a subscription. */
function stubPush(existing: boolean) {
  const subscription = {
    endpoint: "https://fcm.googleapis.com/fcm/send/abc",
    toJSON: () => ({
      endpoint: "https://fcm.googleapis.com/fcm/send/abc",
      keys: { p256dh: "p256", auth: "auth" },
    }),
    unsubscribe: vi.fn(async () => true),
  };
  const pushManager = {
    getSubscription: vi.fn(async () => (existing ? subscription : null)),
    subscribe: vi.fn(async () => subscription),
  };
  const registration = { pushManager };
  vi.stubGlobal("PushManager", function PushManager() {});
  vi.stubGlobal(
    "Notification",
    Object.assign(function Notification() {}, {
      permission: "default",
      requestPermission: vi.fn(async () => "granted"),
    }),
  );
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: {
      ready: Promise.resolve(registration),
      getRegistration: vi.fn(async () => registration),
      controller: null,
    },
  });
  return pushManager;
}

beforeEach(() => resetMemoryStorage());

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "serviceWorker");
  window.history.pushState(null, "", "/portal/");
});

describe("tutor notifications", () => {
  it("turns on push for this phone and registers it", async () => {
    const pushManager = stubPush(false);
    window.history.pushState(null, "", "/portal/tutor/notifications");
    const calls = mockApi(
      routes({
        "POST /api/v1/push-subscriptions": {
          status: 201,
          body: { id: "s2", device: "Linux", push_service: "fcm.googleapis.com" },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Turn on notifications" }));
    expect(await screen.findByText("Push notifications are on for this device.")).toBeVisible();
    expect(pushManager.subscribe).toHaveBeenCalledWith(
      expect.objectContaining({ userVisibleOnly: true }),
    );
    const post = calls.find((c) => c.method === "POST" && c.path === "/api/v1/push-subscriptions");
    expect(post?.body).toMatchObject({
      endpoint: "https://fcm.googleapis.com/fcm/send/abc",
      keys: { p256dh: "p256", auth: "auth" },
    });
  });

  it("sends a test push and lists devices", async () => {
    stubPush(true);
    window.history.pushState(null, "", "/portal/tutor/notifications");
    mockApi(routes({ "POST /api/v1/push-subscriptions/test": { body: { delivered: 2 } } }));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Send a test notification" }));
    expect(await screen.findByText("Sent to 2 devices.")).toBeInTheDocument();
    const devices = screen.getByRole("region", { name: "Devices with notifications on" });
    expect(within(devices).getByRole("button", { name: "Remove Android" })).toBeInTheDocument();
  });

  it("explains Home Screen install on iPhone", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    );
    window.history.pushState(null, "", "/portal/tutor/notifications");
    mockApi(routes());
    render(<App />);
    expect(await screen.findByText("Add the app to your Home Screen first")).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("saves which channels each kind of message uses", async () => {
    window.history.pushState(null, "", "/portal/tutor/notifications");
    const calls = mockApi(
      routes({
        "PUT /api/v1/communication-preferences/mine": (body) => ({
          body: {
            preferences: (
              body as { preferences: { category: string; channels: string[] }[] }
            ).preferences.map((p) => ({ ...p, available: ["email", "sms", "in_app", "push"] })),
          },
        }),
      }),
    );
    render(<App />);
    const lessons = await screen.findByRole("group", { name: "Lessons and jobs" });
    fireEvent.click(within(lessons).getByRole("checkbox", { name: "Text" }));
    const pay = screen.getByRole("group", { name: "Pay" });
    fireEvent.click(within(pay).getByRole("checkbox", { name: "Push" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        preferences: [
          { category: "scheduling", channels: ["email", "in_app", "push"] },
          { category: "billing", channels: ["in_app", "push"] },
        ],
      }),
    );
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });
});
